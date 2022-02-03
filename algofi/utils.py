import os
import json
from random import randint
from enum import Enum
import base64
from algosdk.future.transaction import LogicSigTransaction, assign_group_id
from algosdk import encoding, account, mnemonic
from algosdk.error import AlgodHTTPError
from algosdk.future.transaction import PaymentTxn
from .contract_strings import algofi_manager_strings as manager_strings
from .contract_strings import algofi_market_strings as market_strings

# CONSTANTS
PARAMETER_SCALE_FACTOR = int(1e3)
SCALE_FACTOR = int(1e9)
REWARDS_SCALE_FACTOR = int(1e14)

# contracts abspath
#CONTRACTS_FPATH = os.path.relpath("./v1/contracts.json")
my_path = os.path.abspath(os.path.dirname(__file__))
CONTRACTS_FPATH = os.path.join(my_path, "v1/contracts.json")

class Transactions(Enum):
    MINT = 1
    MINT_TO_COLLATERAL = 2
    ADD_COLLATERAL = 3
    REMOVE_COLLATERAL = 4
    BURN = 5
    REMOVE_COLLATERAL_UNDERLYING = 6
    BORROW = 7
    REPAY_BORROW = 8
    LIQUIDATE = 9
    CLAIM_REWARDS = 10

def get_program(definition, variables=None):
    """
    Return a byte array to be used in LogicSig.
    """
    template = definition['bytecode']
    template_bytes = list(b64decode(template))

    offset = 0
    for v in sorted(definition['variables'], key=lambda v: v['index']):
        name = v['name'].split('TMPL_')[-1].lower()
        value = variables[name]
        start = v['index'] - offset
        end = start + v['length']
        value_encoded = encode_value(value, v['type'])
        value_encoded_len = len(value_encoded)
        diff = v['length'] - value_encoded_len
        offset += diff
        template_bytes[start:end] = list(value_encoded)

    return bytes(template_bytes)


def encode_value(value, type):
    if type == 'int':
        return encode_varint(value)
    raise Exception('Unsupported value type %s!' % type)


def encode_varint(number):
    buf = b''
    while True:
        towrite = number & 0x7f
        number >>= 7
        if number:
            buf += bytes([towrite | 0x80])
        else:
            buf += bytes([towrite])
            break
    return buf


def sign_and_submit_transactions(client, transactions, signed_transactions, sender, sender_sk):
    for i, txn in enumerate(transactions):
        if txn.sender == sender:
            signed_transactions[i] = txn.sign(sender_sk)
    
    txid = client.send_transactions(signed_transactions)
    return wait_for_confirmation(client, txid)


def wait_for_confirmation(client, txid):
    """Waits for a transaction with id txid to complete. Returns dict with transaction information 
    after completion.

    :param client: algod client
    :type client: :class:`AlgodClient`
    :param txid: id of the sent transaction
    :type txid: string
    :return: dict of transaction information
    :rtype: dict
    """
    last_round = client.status().get('last-round')
    txinfo = client.pending_transaction_info(txid)
    while not (txinfo.get('confirmed-round') and txinfo.get('confirmed-round') > 0):
        print("Waiting for confirmation")
        last_round += 1
        client.status_after_block(last_round)
        txinfo = client.pending_transaction_info(txid)
    txinfo['txid'] = txid
    print("Transaction {} confirmed in round {}.".format(txid, txinfo.get('confirmed-round')))
    return txinfo


def int_to_bytes(num):
    return num.to_bytes(8, 'big')


def get_state_int(state, key):
    if type(key) == str:
        key = b64encode(key.encode())
    return state.get(key.decode(), {'uint': 0})['uint']


def get_state_bytes(state, key):
    if type(key) == str:
        key = b64encode(key.encode())
    return state.get(key.decode(), {'bytes': ''})['bytes']


def format_state(state):
    """Returns state dict formatted to human-readable strings

    :param state: dict of state returned by read_local_state or read_global_state
    :type state: dict
    :return: dict of state with keys + values formatted from bytes to utf-8 strings
    :rtype: dict
    """
    formatted = {}
    for item in state:
        key = item['key']
        value = item['value']
        try:
            formatted_key = base64.b64decode(key).decode('utf-8')
        except:
            formatted_key = base64.b64decode(key)
        if value['type'] == 1:
            # byte string
            try:
                formatted_value=base64.b64decode(value['bytes']).decode('utf-8')
            except:
                formatted_value=value['bytes']
            formatted[formatted_key] = formatted_value
        else:
            # integer
            formatted[formatted_key] = value['uint']
    return formatted


def read_local_state(client, address, app_id):
    """Returns dict of local state for address for application with id app_id

    :param client: algod client
    :type client: :class:`AlgodClient`
    :param address: address of account for which to get state
    :type address: string
    :param app_id: id of the application
    :type app_id: int
    :return: dict of local state of address for application with id app_id
    :rtype: dict
    """
    results = client.account_info(address)
    for local_state in results['apps-local-state']:
        if local_state['id'] == app_id:
            if 'key-value' not in local_state:
                return {}
            return format_state(local_state['key-value'])
    return {}


def read_global_state(client, address, app_id):
    """Returns dict of global state for application with id app_id. Address must be that of the creator.

    :param client: algod client
    :type client: :class:`AlgodClient`
    :param address: creator address
    :type address: string
    :param app_id: id of the application
    :type app_id: int
    :return: dict of global state for application with id app_id
    :rtype: dict
    """
    results = client.account_info(address)
    apps_created = results['created-apps']
    for app in apps_created:
        if app['id'] == app_id:
            return format_state(app['params']['global-state'])
    return {}


def get_global_state(client, app_id):
    """Returns dict of global state for application with the given app_id

    :param client: algod client
    :type client: :class:`AlgodClient`
    :param app_id: id of the application
    :type app_id: int
    :return: dict of global state for application with id app_id
    :rtype: dict
    """
    return format_state(client.application_info(app_id)["params"]['global-state'])


def get_staking_contracts(chain):
    """Returns list of supported staking contracts for the specified chain. Pulled from hardcoded values in contracts.json.

    :param chain: network to query data for
    :type chain: string e.g. 'testnet'
    :return: list of supported staking contracts
    :rtype: list
    """
    with open(CONTRACTS_FPATH, 'r') as contracts_file:
        json_file = json.load(contracts_file)[chain]
        staking_contracts = json_file["STAKING_CONTRACTS"] 
        return staking_contracts


def get_ordered_symbols(chain, max=False, max_atomic_opt_in=False):
    """Returns list of supported symbols for the specified chain. Pulled from hardcoded values in contracts.json.

    :param chain: network to query data for
    :type chain: string e.g. 'testnet'
    :param max: max assets?
    :type max: boolean
    :return: list of supported symbols for algofi's protocol on chain
    :rtype: list
    """
    with open(CONTRACTS_FPATH, 'r') as contracts_file:
        json_file = json.load(contracts_file)[chain]
        if max:
            supported_market_count = json_file["maxMarketCount"]
        elif max_atomic_opt_in:
            supported_market_count = json_file["maxAtomicOptInMarketCount"]
        else:
            supported_market_count = json_file["supportedMarketCount"] 
        return json_file['SYMBOLS'][:supported_market_count]


def get_manager_app_id(chain):
    """Returns app id of manager for the specified chain. Pulled from hardcoded values in contracts.json.

    :param chain: network to query data for
    :type chain: string e.g. 'testnet'
    :return: manager app id
    :rtype: int
    """
    with open(CONTRACTS_FPATH, 'r') as contracts_file:
        json_file = json.load(contracts_file)[chain]
        return json_file['managerAppId']


def get_market_app_id(chain, symbol):
    """Returns market app id of symbol for the specified chain. Pulled from hardcoded values in contracts.json.

    :param chain: network to query data for
    :type chain: string e.g. 'testnet'
    :param symbol: symbol to get market data for
    :type symbol: string e.g. 'ALGO'
    :return: market app id
    :rtype: int
    """
    with open(CONTRACTS_FPATH, 'r') as contracts_file:
        json_file = json.load(contracts_file)[chain]
        return json_file['SYMBOL_INFO'][symbol]["marketAppId"]

def get_init_round(chain):
    """Returns init round of algofi protocol for a specified chain. Pulled from hardcoded values in contracts.json.

    :param chain: network to query data for
    :type chain: string e.g. 'testnet'
    :return: init round of algofi protocol on specified chain
    :rtype: string
    """
    with open(CONTRACTS_FPATH, 'r') as contracts_file:
        json_file = json.load(contracts_file)[chain]
        return json_file['initRound']


def prepare_payment_transaction(sender, suggested_params, receiver, amount, rekey_to=None):
    """Returns a :class:`TransactionGroup` object representing a payment group transaction 
    for a given sender, receiver, amount and ability to rekey.

    :param sender: account address for the sender
    :type sender: string
    :param suggested_params: suggested transaction params
    :type suggested_params: :class:`algosdk.future.transaction.SuggestedParams` object
    :param receiver: account address for the receiver
    :type receiver: string
    :param amount: amount of algos to send
    :type amount: int
    :param amount: address to rekey sender to after payment
    :type amount: string
    :return: :class:`TransactionGroup` object representing a payment group transaction
    :rtype: :class:`TransactionGroup`
    """
    txn = PaymentTxn(
            sender=sender,
            sp=suggested_params,
            receiver=receiver,
            amt=amount,
            rekey_to=rekey_to
    )
    txn_group = TransactionGroup([txn])
    return txn_group


def get_new_account():
    """Returns a tuple with a new key, address and passphrase.

    :return: tuple of key, address, passphrase for a new algorand account
    :rtype: tuple
    """
    key, address = account.generate_account()
    passphrase = mnemonic.from_private_key(key)
    return (key, address, passphrase)

def search_global_state(global_state, search_key):
    """Returns value from the encoded global state dict of an application

    :param global_state: global state of an application
    :type global_state: dict
    :param search_key: utf8 key of a value to search for
    :type search_key: string
    :return: value for the given key
    :rtype: byte or int
    """
    for field in global_state:
        key, value = field['key'], field['value']
        if search_key == base64.b64decode(key).decode():
            if value['type'] == 2:
                value = value['uint']
            else:
                value = value['bytes']
            return value
    raise Exception("Key not found")


class TransactionGroup:

    def __init__(self, transactions):
        """Constructor method for :class:`TransactionGroup` class

        :param transactions: list of unsigned transactions
        :type transactions: list
        """
        transactions = assign_group_id(transactions)
        self.transactions = transactions
        self.signed_transactions = [None for _ in self.transactions]

    def sign_with_private_key(self, address, private_key):
        """Signs the transactions with specified private key and saves to class state

        :param address: account address of the user
        :type address: string
        :param private_key: private key of user
        :type private_key: string
        """
        for i, txn in enumerate(self.transactions):
            self.signed_transactions[i] = txn.sign(private_key)
    
    def sign_with_private_keys(self, private_keys):
        """Signs the transactions with specified private key and saves to class state

        :param private_key: private key of user
        :type private_key: string
        """
        assert(len(private_keys) == len(self.transactions))
        for i, txn in enumerate(self.transactions):
            self.signed_transactions[i] = txn.sign(private_keys[i])
        
    def submit(self, algod, wait=False):
        """Submits the signed transactions to network using the algod client

        :param algod: algod client
        :type algod: :class:`AlgodClient`
        :param wait: wait for txn to complete, defaults to False
        :type wait: boolean, optional
        :return: dict of transaction id
        :rtype: dict
        """
        try:
            txid = algod.send_transactions(self.signed_transactions)
        except AlgodHTTPError as e:
            raise Exception(str(e))
        if wait:
            return wait_for_confirmation(algod, txid)
        return {'txid': txid}

def get_accounts_opted_into_app(indexer, app_id):
    """Submits the signed transactions to network using the algod client

    :param indexer: indexer client
    :type indexer: :class:`IndexerClient`
    :param app_id: application id
    :type app_id: int
    :return: list of accounts opted into app
    :rtype: list
    """

    next_page = ""
    accounts = []
    while next_page is not None:
        account_data = indexer.accounts(limit=1000, next_page=next_page, application_id=app_id)
        accounts.extend([account["address"] for account in account_data["accounts"]])
        if "next-token" in account_data:
            next_page = account_data["next-token"]
        else:
            next_page = None
    return accounts
import json
import base64
from algosdk import encoding
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from algosdk.error import AlgodHTTPError
from ..utils import read_local_state, read_global_state, wait_for_confirmation, get_ordered_symbols, \
get_manager_app_id, get_market_app_id, get_init_round, get_staking_contracts
from ..contract_strings import algofi_manager_strings as manager_strings
from ..contract_strings import algofi_market_strings as market_strings

from .api_client import ApiClient
from .manager import Manager
from .market import Market
from .staking_contract import StakingContract

from .optin import prepare_manager_app_optin_transactions
from .add_collateral import prepare_add_collateral_transactions
from .borrow import prepare_borrow_transactions
from .burn import prepare_burn_transactions
from .claim_rewards import prepare_claim_rewards_transactions
from .liquidate import prepare_liquidate_transactions
from .mint import prepare_mint_transactions
from .mint_to_collateral import prepare_mint_to_collateral_transactions
from .remove_collateral import prepare_remove_collateral_transactions
from .remove_collateral_underlying import prepare_remove_collateral_underlying_transactions
from .repay_borrow import prepare_repay_borrow_transactions
from .supply_algos_to_vault import prepare_supply_algos_to_vault_transactions
from .remove_algos_from_vault import prepare_remove_algos_from_vault_transactions
from .sync_vault import prepare_sync_vault_transactions
from .send_governance_transaction import prepare_send_governance_transactions
from .send_keyreg_online_transaction import prepare_send_keyreg_online_transactions
from .send_keyreg_offline_transaction import prepare_send_keyreg_offline_transactions

from .staking import prepare_staking_contract_optin_transactions, \
                     prepare_stake_transactions, \
                     prepare_unstake_transactions, \
                     prepare_claim_staking_rewards_transactions

class Client:

    def __init__(self, algod_client: AlgodClient, indexer_client: IndexerClient,
                 historical_indexer_client: IndexerClient, user_address, chain, use_indexer=True):
        """Constructor method for the generic client.

        :param algod_client: a :class:`AlgodClient` for interacting with the network
        :type algod_client: :class:`AlgodClient`
        :param indexer_client: a :class:`IndexerClient` for interacting with the network
        :type indexer_client: :class:`IndexerClient`
        :param historical_indexer_client: a :class:`IndexerClient` for interacting with the network historically
        :type historical_indexer_client: :class:`IndexerClient`
        :param user_address: address of the user
        :type user_address: string
        :param chain: network type
        :type chain: string
        """

        # constants
        self.SCALE_FACTOR = 1e9
        self.BORROW_SHARES_INIT = 1e3
        self.PARAMETER_SCALE_FACTOR = 1e3

        # clients info
        self.algod = algod_client
        self.indexer = indexer_client
        self.historical_indexer = historical_indexer_client
        self.api_client = ApiClient(algod_client, indexer_client, historical_indexer_client, use_indexer)
        self.chain = chain

        # user info
        self.user_address = user_address

        self.init_round = get_init_round(self.chain)
        self.active_ordered_symbols = get_ordered_symbols(self.chain)
        self.max_ordered_symbols = get_ordered_symbols(self.chain, max=True)
        self.max_atomic_opt_in_ordered_symbols = get_ordered_symbols(self.chain, max_atomic_opt_in=True)

        # manager info
        self.manager = Manager(self.api_client, get_manager_app_id(self.chain))

        # market info
        self.markets = {symbol : Market(self.indexer, self.historical_indexer, get_market_app_id(self.chain, symbol)) for symbol in self.max_ordered_symbols}

        # staking contract info
        self.staking_contract_info = get_staking_contracts(self.chain)
        self.staking_contracts = {name : StakingContract(self.indexer, self.historical_indexer, self.staking_contract_info[name]) for name in self.staking_contract_info.keys()}

    # HELPER FUNCTIONS

    def get_default_params(self):
        """Initializes the transactions parameters for the client.
        """
        params = self.algod.suggested_params()
        params.flat_fee = True
        params.fee = 1000
        return params

    # USER STATE GETTERS

    def get_user_info(self, address=None):
        """Returns a dictionary of information about the user

        :param address: address to get info for
        :type address: string
        :return: A dict of information of the user
        :rtype: dict
        """
        if not address:
            address = self.user_address
        if address:
            try:
                user_info = self.api_client.account_info(address)
                if "apps-local-state" not in user_info:
                    user_info["apps-local-state"] = []
                if "assets" not in user_info:
                    user_info["assets"] = []
                return user_info
            except:
                raise Exception("Account does not exist with address " + address + ".")
        else:
            raise Exception("user_address has not been specified")

    def is_opted_into_app(self, app_id, address=None):
        """Returns a boolean if the user address is opted into an application with id app_id

        :param address: address to get info for
        :type address: string
        :param app_id: id of the application
        :type app_id: int
        :return: boolean if user is opted into an application
        :rtype: boolean
        """
        if not address:
            address = self.user_address
        user_info = self.get_user_info(address)
        return app_id in [x['id'] for x in user_info['apps-local-state']]

    def is_opted_into_asset(self, asset_id, address=None):
        """Returns a boolean if the user address is opted into an asset with id asset_id

        :param address: address to get info for
        :type address: string
        :param asset_id: id of the asset
        :type asset_id: int
        :return: boolean if user is opted into an asset
        :rtype: boolean
        """
        if not address:
            address = self.user_address
        user_info = self.get_user_info(address)
        assets = user_info.get("assets", [])
        return asset_id in [x['asset-id'] for x in assets]

    def get_user_balances(self, address=None):
        """Returns a dictionary of user balances by asset id

        :param address: address to get info for
        :type address: string
        :return: amount of asset
        :rtype: int
        """
        if not address:
            address = self.user_address
        user_info = self.get_user_info(address)
        balances = {asset["asset-id"] : asset["amount"] for asset in user_info["assets"]}
        balances[1] = user_info["amount"]
        return balances

    def get_user_balance(self, asset_id=1, address=None):
        """Returns a amount of asset in user's balance with asset id asset_id

        :param address: address to get info for
        :type address: string
        :param asset_id: id of the asset, default to None (algo)
        :type asset_id: int, optional
        :return: amount of asset
        :rtype: int
        """
        if not address:
            address = self.user_address
        return self.get_user_balances(address).get(asset_id, 0)

    def get_user_state(self, address=None):
        """Returns a dictionary with the lending market state for a given address (must be opted in)

        :param address: address to get info for. If None will use address supplied when creating client
        :type address: string
        :return: state
        :rtype: dict
        """
        result = {}
        if not address:
            address = self.user_address
        result["manager"] = self.manager.get_user_state(address)
        storage_address = self.manager.get_storage_address(address)
        for symbol in self.active_ordered_symbols:
            result[symbol] = self.markets[symbol].get_storage_state(storage_address)
        return result

    def get_storage_state(self, storage_address=None, block=None, include_manager=True):
        """Returns a dictionary with the lending market state for a given storage address

        :param storage_address: address to get info for. If None will use address supplied when creating client
        :type storage_address: string

        :return: state
        :rtype: dict
        """
        result = {}
        if not storage_address:
            storage_address = self.manager.get_storage_address(self.user_address)
        if include_manager:
            result["manager"] = self.manager.get_storage_state(storage_address, block=block)
        supported_market_count = self.manager.get_supported_market_count(block=block)
        active_markets = self.active_ordered_symbols[:supported_market_count]
        for symbol in active_markets:
            result[symbol] = self.markets[symbol].get_storage_state(storage_address, block=block)
        return result

    def get_user_staking_contract_state(self, staking_contract_name, address=None):
        """Returns a dictionary with the staking contract state for the named staking contract and selected address

        :param staking_contract_name: name of staking contract to query
        :type staking_contract_name: string
        :param address: address to get info for. If None will use address supplied when creating client
        :type address: string
        :return: state
        :rtype: dict
        """
        result = {}
        if not address:
            address = self.user_address
        return self.staking_contracts[staking_contract_name].get_user_state(address)

    # GETTERS

    def get_manager(self):
        """Returns the manager object

        :return: manager
        :rtype: :class:`Manager`
        """
        return self.manager

    def get_market(self, symbol):
        """Returns the market object for the given symbol

        :param symbol: market symbol
        :type symbol: string
        :return: market
        :rtype: :class:`Market`
        """
        return self.markets[symbol]

    def get_active_markets(self):
        """Returns dictionary of active markets by symbol

        :return: markets dictionary
        :rtype: dict
        """
        return dict(filter(lambda elem: elem[0] in self.active_ordered_symbols, self.markets.items()))

    def get_staking_contract(self, name):
        """Returns the manager object

        :param name: staking contract name
        :type name: string
        :return: staking contract
        :rtype: :class:`StakingContract`
        """
        return self.staking_contracts[name]

    def get_staking_contracts(self):
        """Returns the manager object

        :return: staking contracts dictionary
        :rtype: dict
        """
        return self.staking_contracts

    def get_asset(self, symbol):
        """Returns the asset object for the requested symbol.

        :param symbol: symbol of the asset
        :type symbol: string
        :return: Asset object
        :rtype: :class:`Asset`
        """
        if symbol not in self.active_ordered_symbols:
            raise Exception("Unsupported asset")
        return self.markets[symbol].get_asset()

    def get_max_atomic_opt_in_market_app_ids(self):
        """Returns the max opt in market application ids.

        :return: list of max opt in market application ids
        :rtype: list
        """
        return [self.markets[symbol].get_market_app_id() for symbol in self.max_atomic_opt_in_ordered_symbols]

    def get_active_assets(self):
        """Returns a dictionary of the asset objects for each active market

        :return: dictionary of asset objects
        """
        return {symbol : market.get_asset() for symbol, market in self.get_active_markets().items()}

    def get_active_asset_ids(self):
        """Returns the active asset ids.

        :return: list of active asset ids
        :rtype: list
        """
        return [asset.get_underlying_asset_id() for asset in self.get_active_assets().values()]

    def get_active_bank_asset_ids(self):
        """Returns the active bank asset ids.

        :return: list of active bank asset ids
        :rtype: list
        """
        return [asset.get_bank_asset_id() for asset in self.get_active_assets().values()]

    def get_active_ordered_symbols(self):
        """Returns the list of symbols of the active assets

        :return: list of symbols for active assets
        :rtype: list
        """
        return self.active_ordered_symbols

    def get_raw_prices(self):
        """Returns a dictionary of raw oracle prices of the active assets pulled from their oracles

        :return: dictionary of int prices
        :rtype: dict
        """
        return {symbol : market.get_asset().get_raw_price() for symbol, market in self.get_active_markets().items()}

    def get_prices(self):
        """Returns a dictionary of dollarized float prices of the active assets pulled from their oracles

        :return: dictionary of int prices
        :rtype: dict
        """
        return {symbol : market.get_asset().get_price() for symbol, market in self.get_active_markets().items()}

    # INDEXER HELPERS

    def get_storage_accounts(self, staking_contract_name=None, verbose=False):
        """Returns a list of storage accounts for the given manager app id

        :return: list of storage accounts
        :rtype: list
        """
        next_page = ""
        accounts = []
        user_address = base64.b64encode(bytes(manager_strings.user_address, "utf-8")).decode("utf-8")

        if staking_contract_name is None:
            app_id = list(self.get_active_markets().values())[0].get_market_app_id()
        else:
            app_id = self.get_staking_contract(staking_contract_name).get_manager_app_id()

        while next_page is not None:
            account_data = self.indexer.accounts(limit=1000, next_page=next_page, application_id=app_id)
            # filter on accounts with b'ua' in their local state for app_id
            accounts_filtered = []
            for account in account_data["accounts"]:
                user_local_state = account.get("apps-local-state",[])
                for app_local_state in user_local_state:
                    if app_local_state["id"] == self.manager.manager_app_id:
                        fields = app_local_state.get("key-value", [])
                        for field in fields:
                            key = field.get("key", None)
                            if key == user_address:
                                accounts_filtered.append(account)
            accounts.extend([(account if verbose else account["address"]) for account in accounts_filtered])

            if "next-token" in account_data:
                next_page = account_data["next-token"]
            else:
                next_page = None

        return accounts

    # TRANSACTION HELPERS

    def get_active_oracle_app_ids(self):
        """Returns the list of active oracle app ids

        :return: list of active oracle app ids
        :rtype: list
        """
        return [market.get_asset().get_oracle_app_id() for market in self.get_active_markets().values()]

    def get_active_market_app_ids(self):
        """Returns the list of the active market app ids

        :return: list of active market_app_ids
        :rtype: list
        """
        return [market.get_market_app_id() for market in self.get_active_markets().values()]

    def get_active_market_addresses(self):
        """Returns the list of the active market addresses

        :return: list of active market_addresses
        :rtype: list
        """
        return [market.get_market_address() for market in self.get_active_markets().values()]

    # TRANSACTION BUILDERS

    def prepare_optin_transactions(self, storage_address, address=None):
        """Returns an opt in transaction group

        :param storage_address: storage address to fund and rekey
        :type address: string
        :param address: defaults to client user address. address to send add_collateral transaction group from
        :type address: string
        :return: opt in transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        return prepare_manager_app_optin_transactions(self.manager.get_manager_app_id(),
                                                      self.get_max_atomic_opt_in_market_app_ids(),
                                                      address,
                                                      storage_address,
                                                      self.get_default_params())

    def prepare_add_collateral_transactions(self, symbol, amount, address=None):
        """Returns an add_collateral transaction group

        :param symbol: symbol to add collateral with
        :type symbol: string
        :param amount: amount of collateral to add
        :type amount: int
        :param address: defaults to client user address. address to send add_collateral transaction group from
        :type address: string
        :return: add_collateral transaction group
        :rtype: :class:`TransactionGroup`
        """
        assert symbol != 'vALGO', 'Cannot perform operation on Algo Vault'
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_add_collateral_transactions(address,
                                                   self.get_default_params(),
                                                   self.manager.get_storage_address(address),
                                                   amount,
                                                   market.get_asset().get_bank_asset_id(),
                                                   self.manager.get_manager_app_id(),
                                                   market.get_market_app_id(),
                                                   market.get_market_address(),
                                                   self.get_active_market_app_ids(),
                                                   self.get_active_oracle_app_ids())

    def prepare_borrow_transactions(self, symbol, amount, address=None):
        """Returns a borrow transaction group

        :param symbol: symbol to borrow
        :type symbol: string
        :param amount: amount to borrow
        :type amount: int
        :param address: defaults to client user address. address to send borrow transaction group from
        :type address: string
        :return: borrow transaction group
        :rtype: :class:`TransactionGroup`
        """
        assert symbol != 'vALGO', 'Cannot perform operation on Algo Vault'
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_borrow_transactions(address,
                                           self.get_default_params(),
                                           self.manager.get_storage_address(address),
                                           amount,
                                           market.get_asset().get_underlying_asset_id(),
                                           self.manager.get_manager_app_id(),
                                           market.get_market_app_id(),
                                           self.get_active_market_app_ids(),
                                           self.get_active_oracle_app_ids())


    def prepare_burn_transactions(self, symbol, amount, address=None):
        """Returns a burn transaction group

        :param symbol: symbol to burn
        :type symbol: string
        :param amount: amount of bAsset to burn
        :type amount: int
        :param address: defaults to client user address. address to send burn transaction group from
        :type address: string
        :return: burn transaction group
        :rtype: :class:`TransactionGroup`
        """
        assert symbol != 'vALGO', 'Cannot perform operation on Algo Vault'
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_burn_transactions(address,
                                         self.get_default_params(),
                                         self.manager.get_storage_address(address),
                                         amount,
                                         market.get_asset().get_underlying_asset_id(),
                                         market.get_asset().get_bank_asset_id(),
                                         self.manager.get_manager_app_id(),
                                         market.get_market_app_id(),
                                         market.get_market_address(),
                                         self.get_active_market_app_ids(),
                                         self.get_active_oracle_app_ids())

    def prepare_claim_rewards_transactions(self, address=None):
        """Returns a claim_rewards transaction group

        :param address: defaults to client user address. address to send claim_rewards from
        :type address: string
        :return: claim_rewards transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        return prepare_claim_rewards_transactions(address,
                                                  self.get_default_params(),
                                                  self.manager.get_storage_address(address),
                                                  self.manager.get_manager_app_id(),
                                                  self.get_active_market_app_ids(),
                                                  self.get_active_oracle_app_ids(),
                                                  self.manager.get_rewards_program().get_rewards_asset_ids())

    def prepare_liquidate_transactions(self, target_storage_address, borrow_symbol, amount, collateral_symbol, address=None):
        """Returns a liquidate transaction group
        NOTE: seizing vALGO collateral returns ALGOs not bAssets. all other markets return bAssets.

        :param target_storage_address: storage address to liquidate
        :type target_storage_address: string
        :param borrow_symbol: symbol to repay
        :type borrow_symbol: string
        :param amount: amount to repay
        :type amount: int
        :param collateral_symbol: symbol to sieze collateral from
        :type collateral_symbol: string
        :param address: defaults to client user address. address to send liquidate transaction group from
        :type address: string
        :return: liquidate transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        borrow_market = self.get_market(borrow_symbol)
        params = self.get_default_params()
        collateral_market = self.get_market(collateral_symbol)

        return prepare_liquidate_transactions(address,
                                              params,
                                              self.manager.get_storage_address(address),
                                              target_storage_address,
                                              amount,
                                              self.manager.get_manager_app_id(),
                                              borrow_market.get_market_app_id(),
                                              borrow_market.get_market_address(),
                                              collateral_market.get_market_app_id(),
                                              self.get_active_market_app_ids(),
                                              self.get_active_oracle_app_ids(),
                                              collateral_market.get_asset().get_bank_asset_id(),
                                              borrow_market.get_asset().get_underlying_asset_id() if borrow_symbol != "ALGO" else None,
                                              liquidate_update_fee=3000 if collateral_symbol == 'vALGO' else 1000)

    def prepare_mint_transactions(self, symbol, amount, address=None):
        """Returns a mint transaction group

        :param symbol: symbol to mint
        :type symbol: string
        :param amount: amount of mint
        :type amount: int
        :param address: defaults to client user address. address to send mint transaction group from
        :type address: string
        :return: mint transaction group
        :rtype: :class:`TransactionGroup`
        """
        assert symbol != 'vALGO', 'Cannot perform operation on Algo Vault'
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_mint_transactions(address,
                                         self.get_default_params(),
                                         self.manager.get_storage_address(address),
                                         amount,
                                         market.get_asset().get_bank_asset_id(),
                                         self.manager.get_manager_app_id(),
                                         market.get_market_app_id(),
                                         market.get_market_address(),
                                         self.get_active_market_app_ids(),
                                         self.get_active_oracle_app_ids(),
                                         market.get_asset().get_underlying_asset_id() if symbol != "ALGO" else None)

    def prepare_mint_to_collateral_transactions(self, symbol, amount, address=None):
        """Returns a mint_to_collateral transaction group

        :param symbol: symbol to mint to collateral
        :type symbol: string
        :param amount: amount to mint to collateral
        :type amount: int
        :param address: defaults to client user address. address to send mint_to_collateral transaction group from
        :type address: string
        :return: mint_to_collateral transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_mint_to_collateral_transactions(address,
                                                       self.get_default_params(),
                                                       self.manager.get_storage_address(address),
                                                       amount,
                                                       self.manager.get_manager_app_id(),
                                                       market.get_market_app_id(),
                                                       market.get_market_address(),
                                                       self.get_active_market_app_ids(),
                                                       self.get_active_oracle_app_ids(),
                                                       market.get_asset().get_underlying_asset_id() if symbol != "ALGO" else None)

    def prepare_remove_collateral_transactions(self, symbol, amount, address=None):
        """Returns a remove_collateral transaction group

        :param symbol: symbol to remove collateral from
        :type symbol: string
        :param amount: amount of collateral to remove
        :type amount: int
        :param address: defaults to client user address. address to send remove_collateral transaction group from
        :type address: string
        :return: remove_collateral transaction group
        :rtype: :class:`TransactionGroup`
        """
        assert symbol != 'vALGO', 'Cannot perform operation on Algo Vault'
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_remove_collateral_transactions(address,
                                                      self.get_default_params(),
                                                      self.manager.get_storage_address(address),
                                                      amount,
                                                      market.get_asset().get_bank_asset_id(),
                                                      self.manager.get_manager_app_id(),
                                                      market.get_market_app_id(),
                                                      self.get_active_market_app_ids(),
                                                      self.get_active_oracle_app_ids())

    def prepare_remove_collateral_underlying_transactions(self, symbol, amount, address=None):
        """Returns a remove_collateral_underlying transaction group

        :param symbol: symbol to remove collateral from
        :type symbol: string
        :param amount: amount of collateral to remove
        :type amount: int
        :param address: defaults to client user address. address to send remove_collateral_underlying transaction group from
        :type address: string
        :return: remove_collateral_underlying transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_remove_collateral_underlying_transactions(address,
                                                                 self.get_default_params(),
                                                                 self.manager.get_storage_address(address),
                                                                 amount,
                                                                 market.get_asset().get_underlying_asset_id(),
                                                                 self.manager.get_manager_app_id(),
                                                                 market.get_market_app_id(),
                                                                 self.get_active_market_app_ids(),
                                                                 self.get_active_oracle_app_ids())

    def prepare_repay_borrow_transactions(self, symbol, amount, address=None):
        """Returns a repay_borrow transaction group

        :param symbol: symbol to repay
        :type symbol: string
        :param amount: amount of repay
        :type amount: int
        :param address: defaults to client user address. address to send repay_borrow transaction group from
        :type address: string
        :return: repay_borrow transaction group
        :rtype: :class:`TransactionGroup`
        """
        assert symbol != 'vALGO', 'Cannot perform operation on Algo Vault'
        if not address:
            address = self.user_address
        market = self.get_market(symbol)
        return prepare_repay_borrow_transactions(address,
                                                 self.get_default_params(),
                                                 self.manager.get_storage_address(address),
                                                 amount,
                                                 self.manager.get_manager_app_id(),
                                                 market.get_market_app_id(),
                                                 market.get_market_address(),
                                                 self.get_active_market_app_ids(),
                                                 self.get_active_oracle_app_ids(),
                                                 market.get_asset().get_underlying_asset_id() if symbol != "ALGO" else None)

    # STAKING TRANSACTION BUILDERS

    def prepare_staking_contract_optin_transactions(self, staking_contract_name, storage_address, address=None):
        """Returns a staking contract optin transaction group

        :param staking_contract_name: name of staking contract to opt in to
        :type staking_contract_name: string
        :param storage_address: storage address to fund and rekey
        :type address: string
        :param address: defaults to client user address. address to create optin transaction group for
        :type address: string
        :return: staking contract opt in transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        staking_contract = self.get_staking_contract(staking_contract_name)
        return prepare_staking_contract_optin_transactions(staking_contract.get_manager_app_id(),
                                                           staking_contract.get_market_app_id(),
                                                           address,
                                                           storage_address,
                                                           self.get_default_params())

    def prepare_stake_transactions(self, staking_contract_name, amount, address=None):
        """Returns a staking contract stake transaction group

        :param staking_contract_name: name of staking contract to stake on
        :type staking_contract_name: string
        :param amount: amount of stake
        :type amount: int
        :param address: defaults to client user address. address to send stake transaction group from
        :type address: string
        :return: stake transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        staking_contract = self.get_staking_contract(staking_contract_name)
        asset_id = staking_contract.get_asset().get_underlying_asset_id()
        return prepare_stake_transactions(address,
                                          self.get_default_params(),
                                          staking_contract.get_storage_address(address),
                                          amount,
                                          staking_contract.get_manager_app_id(),
                                          staking_contract.get_market_app_id(),
                                          staking_contract.get_market_address(),
                                          staking_contract.get_oracle_app_id(),
                                          asset_id if asset_id > 1 else None)

    def prepare_unstake_transactions(self, staking_contract_name, amount, address=None):
        """Returns a staking contract unstake transaction group

        :param staking_contract_name: name of staking contract to unstake on
        :type staking_contract_name: string
        :param amount: amount of unstake
        :type amount: int
        :param address: defaults to client user address. address to send unstake transaction group from
        :type address: string
        :return: unstake transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        staking_contract = self.get_staking_contract(staking_contract_name)
        asset_id = staking_contract.get_asset().get_underlying_asset_id()
        return prepare_unstake_transactions(address,
                                            self.get_default_params(),
                                            staking_contract.get_storage_address(address),
                                            amount,
                                            staking_contract.get_manager_app_id(),
                                            staking_contract.get_market_app_id(),
                                            staking_contract.get_oracle_app_id(),
                                            asset_id if asset_id > 1 else None)

    def prepare_claim_staking_rewards_transactions(self, staking_contract_name, address=None):
        """Returns a staking contract claim rewards transaction group

        :param staking_contract_name: name of staking contract to unstake on
        :type staking_contract_name: string
        :param address: defaults to client user address. address to send claim rewards transaction group from
        :type address: string
        :return: unstake transaction group
        :rtype: :class:`TransactionGroup`
        """
        if not address:
            address = self.user_address
        staking_contract = self.get_staking_contract(staking_contract_name)
        asset_id = staking_contract.get_asset().get_underlying_asset_id()
        return prepare_claim_staking_rewards_transactions(address,
                                                          self.get_default_params(),
                                                          staking_contract.get_storage_address(address),
                                                          staking_contract.get_manager_app_id(),
                                                          staking_contract.get_market_app_id(),
                                                          staking_contract.get_oracle_app_id(),
                                                          staking_contract.get_rewards_program().get_rewards_asset_ids())

    def prepare_supply_algos_to_vault_transactions(self, amount, address=None):
        """Returns supply algos to vault group transaction

        :param amount: amount of algos in base units
        :type amount: int
        :param address: defaults to client user address. address to send supply algos to vault group transaction from.
        :type address: string
        :return: supply algos to vault transaction group
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address
        market = self.get_market("vALGO")
        return prepare_supply_algos_to_vault_transactions(address,
                                                          self.get_default_params(),
                                                          self.manager.get_storage_address(address),
                                                          amount,
                                                          self.manager.get_manager_app_id(),
                                                          market.get_market_app_id(),
                                                          self.get_active_market_app_ids(),
                                                          self.get_active_oracle_app_ids())

    def prepare_remove_algos_from_vault_transactions(self, amount, address=None):
        """Returns a staking contract claim rewards transaction group

        :param amount: amount of algos in base units
        :type amount: int
        :param address: defaults to client user address. address to send remove algos from vault group transaction from.
        :type address: string
        :return: remove algos from vault transaction group
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address
        market = self.get_market("vALGO")
        return prepare_remove_algos_from_vault_transactions(address,
                                                            self.get_default_params(),
                                                            self.manager.get_storage_address(address),
                                                            amount,
                                                            self.manager.get_manager_app_id(),
                                                            market.get_market_app_id(),
                                                            self.get_active_market_app_ids(),
                                                            self.get_active_oracle_app_ids())

    def prepare_sync_vault_transactions(self, address=None):
        """Returns a sync vault transactions group

        :param address: defaults to client user address. address to send sync vault group transaction from.
        :type address: string
        :return: sync vault group transaction
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address
        market = self.get_market("vALGO")
        return prepare_sync_vault_transactions(address,
                                               self.get_default_params(),
                                               self.manager.get_storage_address(address),
                                               self.manager.get_manager_app_id(),
                                               market.get_market_app_id(),
                                               self.get_active_market_app_ids(),
                                               self.get_active_oracle_app_ids())

    def prepare_send_governance_commitment_transactions(self, governance_address, commitment_amount, address=None, beneficiary=None, check_vault_balance=True):
        """Returns a send governance commitment group transaction. A zero-value PaymentTxn with formatted notes field.
        Format for notes field can be found within Algorand Foundation Governance Spec at
        <https://github.com/algorandfoundation/governance/blob/main/af-gov1-spec.md>

        :param governance_address: governance address to send commitment txn to. Get governance address from <https://governance.algorand.foundation/api/periods>
        within the relevant period "sign_up_address"
        :type governance_address: string
        :param commitment_amount: amount of ALGOs (in microalgos) to commit to governance
        :type commitment_amount: int
        :param address: defaults to client user address. address to send send governance commitment transaction group from.
        this is the primary account address for Algofi, not the vault account address from which the commitment inner transaction will originate.
        :type address: string, optional
        :param beneficiary: specify a beneficiary of the governance rewards. governance rewards will be sent from the Algorand Foundation
        to this address at the end of governance if the vault account is eligible for rewards.
        :type beneficiary: string, optional
        :param check_vault_balance: checks the ALGO balance of the Vault. raises exception if commitment amount > the ALGO balance of the Vault account.
        :type check_vault_balance: boolean, default True
        :return: send governance commitment transaction group
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address

        # get balance of vault account
        vault_address = self.manager.get_storage_address(address)
        vault_account_algo_balance = self.get_user_balance(asset_id=1, address=vault_address)
        if commitment_amount > vault_account_algo_balance:
            raise Exception("Commitment amount of " + str(commitment_amount) + " microAlgos exceeds ALGO balance of vault with address " + \
                            vault_address + " (balance: " + str(vault_account_algo_balance) + ")")

        # prepare note based on commitment amount
        # without beneficary: af/gov1:j{"com":<n>}
        # with beneficary: af/gov1:j{"com":nnn,"bnf":"aaa"}
        # see spec for format at https://github.com/algorandfoundation/governance/blob/main/af-gov1-spec.md

        if beneficiary:
            note = b'af/gov1:j{"com":%s,"bnf":"%s"}' % (bytes(str(commitment_amount),"utf-8"),bytes(beneficiary,"utf-8"))
        else:
            note = b'af/gov1:j{"com":%s}' % (bytes(str(commitment_amount), "utf-8"))

        return prepare_send_governance_transactions(address,
                                                    self.get_default_params(),
                                                    self.manager.get_storage_address(address),
                                                    governance_address,
                                                    note,
                                                    self.manager.get_manager_app_id(),
                                                    self.get_active_market_app_ids(),
                                                    self.get_active_oracle_app_ids())

    def prepare_send_governance_vote_transactions(self, governance_address, note, address=None):
        """Returns a send governance vote group transaction. A zero-value PaymentTxn with formatted notes field.
        Format for voting notes field can be found within Algorand Foundation Governance Spec at
        <https://github.com/algorandfoundation/governance/blob/main/af-gov1-spec.md>

        :param governance_address: governance address to send vote txn to. Get governance address from <https://governance.algorand.foundation/api/periods>
        within the relevant period "sign_up_address"
        :type governance_address: string
        :param note: notes field for voting in governance. see spec for voting notes field at
        https://github.com/algorandfoundation/governance/blob/main/af-gov1-spec.md
        format is af/gov1:j[idx,q1,q2,...]
        idx is the voting session index which can be found at https://governance.algorand.foundation/api/periods
        under the proper governance period within "voting_sessions" under the "id" field
        q1,q2 are votes to the specific measures within a given voting session
        example 1 (vote with all ALGOs on choice "a" in measure 1 and choice "c" in measure 2): af/gov1:j[4,"a","c"]
        example 2 (vote choice "a" with 100 microalgos and choice "b" with 900 microalgos in measure 1; vote choice "c" with all microalgos in measure 2): af/gov1:j[4,{"a":100,"b":900},"c"]
        NOTE: in example 2, voting with less than full commitment requires that the full commitment is distributing across all choices. for example, if
        you commit 1000 microalgos via the Vault, during voting you must use all 1000 microalgos in voting. in a 2-choice vote, you could not vote choice "a"
        with 100 and choice "b" with 899 microalgos. the sum must be 1000 microalgos (100 + 899 = 999 != 1000)
        :type note: bytes
        :param address: defaults to client user address. address to send send governance vote transaction group from.
        this is the primary account address for Algofi, not the vault account address from which the vote inner transaction will originate.
        :type address: string, optional
        :return: send governance vote transaction group
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address

        return prepare_send_governance_transactions(address,
                                                    self.get_default_params(),
                                                    self.manager.get_storage_address(address),
                                                    governance_address,
                                                    note,
                                                    self.manager.get_manager_app_id(),
                                                    self.get_active_market_app_ids(),
                                                    self.get_active_oracle_app_ids())

    def prepare_send_keyreg_online_transactions(self, vote_pk, selection_pk, state_proof_pk, vote_first, vote_last, vote_key_dilution, address=None):
        """Returns a send keyreg online group transaction

        :param vote_pk: vote key for consensus (generated on participation node)
        :type vote_pk: bytes
        :param selection_pk: selection key for consensus (generated on participation node)
        :type selection_pk: bytes
        :param state_proof_pk: state proof key for consensus (generated on participation node)
        :type state_proof_pk: bytes
        :param vote_first: first round at which account votes
        :type vote_first: int
        :param vote_last: last round at which account votes
        :type vote_last: int
        :param vote_key_dilution: key dilution
        :type vote_key_dilution: int
        :param address: defaults to client user address. address to send send keyreg online group transaction from.
        :type address: string
        :return: send keyreg group transaction
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address
        return prepare_send_keyreg_online_transactions(address,
                                                       self.get_default_params(),
                                                       self.manager.get_storage_address(address),
                                                       vote_pk,
                                                       selection_pk,
                                                       state_proof_pk,
                                                       vote_first,
                                                       vote_last,
                                                       vote_key_dilution,
                                                       self.manager.get_manager_app_id(),
                                                       self.get_active_market_app_ids(),
                                                       self.get_active_oracle_app_ids())

    def prepare_send_keyreg_offline_transactions(self, address=None):
        """Returns a send keyreg offline group transaction

        :param address: defaults to client user address. address to send send keyreg offline group transaction from.
        :type address: string
        :return: send keyreg offline group transaction
        :rtype: :class:`TransactionGroup`
        """

        if not address:
            address = self.user_address
        return prepare_send_keyreg_offline_transactions(address,
                                                        self.get_default_params(),
                                                        self.manager.get_storage_address(address),
                                                        self.manager.get_manager_app_id(),
                                                        self.get_active_market_app_ids(),
                                                        self.get_active_oracle_app_ids())



    # TRANSACTION SUBMITTER

    def submit(self, transaction_group, wait=False):
        """Submits group transaction to network + waits for completion if specified. Fails if transaction
        fails or wait operation times out.

        :param transaction_group: a list of signed transactions
        :type transaction_group: list
        :param wait: boolean whether to wait for transaction to be completed, defaults to False
        :type wait: boolean, optional
        :return: dict of the transaction id {"txid": txid}
        :rtype: dict
        """
        try:
            txid = self.algod.send_transactions(transaction_group)
        except AlgodHTTPError as e:
            raise Exception(json.loads(e.args[0])['message']) from None
        if wait:
            return wait_for_confirmation(self.algod, txid)
        return {'txid': txid}



class AlgofiTestnetClient(Client):
    def __init__(self, algod_client=None, indexer_client=None, user_address=None, use_indexer=True):
        """Constructor method for the testnet generic client.

        :param algod_client: a :class:`AlgodClient` for interacting with the network
        :type algod_client: :class:`AlgodClient`
        :param indexer_client: a :class:`IndexerClient` for interacting with the network
        :type indexer_client: :class:`IndexerClient`
        :param user_address: address of the user
        :type user_address: string
        """
        historical_indexer_client = IndexerClient("", "https://indexer.testnet.algoexplorerapi.io/", headers={"User-Agent": "algosdk"})
        if algod_client is None:
            algod_client = AlgodClient("", "https://node.testnet.algoexplorerapi.io", headers={"User-Agent": "algosdk"})
        if indexer_client is None:
            indexer_client = IndexerClient("", "https://algoindexer.testnet.algoexplorerapi.io", headers={"User-Agent": "algosdk"})
        super().__init__(algod_client, indexer_client=indexer_client, historical_indexer_client=historical_indexer_client,
                         user_address=user_address, chain="testnet", use_indexer=use_indexer)

class AlgofiMainnetClient(Client):
    def __init__(self, algod_client=None, indexer_client=None, user_address=None, use_indexer=True):
        """Constructor method for the mainnet generic client.

        :param algod_client: a :class:`AlgodClient` for interacting with the network
        :type algod_client: :class:`AlgodClient`
        :param indexer_client: a :class:`IndexerClient` for interacting with the network
        :type indexer_client: :class:`IndexerClient`
        :param user_address: address of the user
        :type user_address: string
        """
        historical_indexer_client = IndexerClient("", "https://indexer.algoexplorerapi.io/", headers={"User-Agent": "algosdk"})
        if algod_client is None:
            algod_client = AlgodClient("", "https://node.algoexplorerapi.io", headers={"User-Agent": "algosdk"})
        if indexer_client is None:
            indexer_client = IndexerClient("", "https://algoindexer.algoexplorerapi.io", headers={"User-Agent": "algosdk"})
        super().__init__(algod_client, indexer_client=indexer_client, historical_indexer_client=historical_indexer_client,
                         user_address=user_address, chain="mainnet", use_indexer=use_indexer)

import json
import base64
from algosdk import encoding, logic
from algosdk.v2client.algod import AlgodClient
from algosdk.v2client.indexer import IndexerClient
from .api_client import ApiClient
from ..utils import read_local_state, read_global_state, get_global_state_field, SCALE_FACTOR
from ..contract_strings import algofi_manager_strings as manager_strings
from ..contract_strings import algofi_market_strings as market_strings
from .rewards_program import RewardsProgram

class Manager:
    def __init__(self, api_client: ApiClient, manager_app_id):
        """Constructor method for manager object.

        :param indexer_client: a :class:`IndexerClient` for interacting with the network
        :type indexer_client: :class:`IndexerClient`
        :param historical_indexer_client: a :class:`IndexerClient` for interacting with the network
        :type historical_indexer_client: :class:`IndexerClient`
        :param manager_app_id: manager app id
        :type manager_app_id: int
        """

        self.indexer = api_client.indexer
        self.historical_indexer = api_client.historical_indexer
        self.api_client = api_client

        self.manager_app_id = manager_app_id
        self.manager_address = logic.get_application_address(self.manager_app_id)

        # read market global state
        self.update_global_state()

    def update_global_state(self, block=None):
        """Method to fetch most recent manager global state.

        :param block: block at which to get historical data
        :type block: int, optional
        """
        manager_state = read_global_state(self.api_client, self.manager_app_id, block=block)
        self.rewards_program = RewardsProgram(self.indexer, self.historical_indexer, manager_state)
        self.supported_market_count = manager_state.get(manager_strings.supported_market_count, None)

    # GETTERS

    def get_manager_app_id(self):
        """Return manager app id

        :return: manager app id
        :rtype: int
        """
        return self.manager_app_id

    def get_manager_address(self):
        """Return manager address

        :return: manager address
        :rtype: string
        """
        return self.manager_address

    def get_rewards_program(self):
        """Return a list of current rewards program

        :return: rewards program
        :rtype: :class:`RewardsProgram
        """
        return self.rewards_program

    def get_supported_market_count(self, block=None):
        """Return the supported market count

        :param block: block at which to get historical data
        :type block: int, optional
        :return: supported market count
        :rtype: int
        """
        if block:
            return get_global_state_field(self.historical_indexer, self.manager_app_id, manager_strings.supported_market_count, block=block)
        else:
            return self.supported_market_count

    # USER FUNCTIONS

    def get_storage_address(self, address):
        """Returns the storage address for the client user

        :param address: address to get info for
        :type address: string
        :return: storage account address for user
        :rtype: string
        """
        user_manager_state = read_local_state(self.indexer, address, self.manager_app_id)
        raw_storage_address = user_manager_state.get(manager_strings.user_storage_address, None)
        if not raw_storage_address:
            raise Exception("No storage address found")
        return encoding.encode_address(base64.b64decode(raw_storage_address.strip()))

    def get_user_state(self, address, block=None):
        """Returns the market local state for address.

        :param address: address to get info for
        :type address: string
        :param block: block at which to get historical data
        :type block: int, optional
        :return: market local state for address
        :rtype: dict
        """
        storage_address = self.get_storage_address(address)
        return self.get_storage_state(storage_address, block=block)

    def get_storage_state(self, storage_address, block=None):
        """Returns the market local state for storage address.

        :param storage_address: storage_address to get info for
        :type storage_address: string
        :param block: block at which to get historical data
        :type block: int, optional
        :return: market local state for address
        :rtype: dict
        """
        result = {}
        indexer_client = self.historical_indexer if block else self.indexer
        user_state = read_local_state(indexer_client, storage_address, self.manager_app_id, block=block)
        result["user_global_max_borrow_in_dollars"] = user_state.get(manager_strings.user_global_max_borrow_in_dollars, 0)
        result["user_global_borrowed_in_dollars"] = user_state.get(manager_strings.user_global_borrowed_in_dollars, 0)
        return result

    def get_user_unrealized_rewards(self, address, markets):
        """Returns projected unrealized rewards for a user address

        :param address: account address of user to get unrealized rewards for
        :type address: string
        :param markets: list of markets to get unrealized rewards for
        :type markets: list
        :return: tuple of primary and secondary unrealized rewards
        :rtype: (int, int)
        """
        storage_address = self.get_storage_address(address)
        return self.get_storage_unrealized_rewards(storage_address, markets)

    def get_storage_unrealized_rewards(self, storage_address, markets):
        """Returns projected unrealized rewards for a storage address

        :param storage_address: account storage address of user to get unrealized rewards for
        :type storage_address: string
        :param markets: list of markets to get unrealized rewards for
        :type markets: list
        :return: tuple of primary and secondary unrealized rewards
        :rtype: (int, int)
        """
        return self.get_rewards_program().get_storage_unrealized_rewards(storage_address, self, markets)

import json
import base64
from algosdk import encoding
from algosdk.v2client.algod import AlgodClient
from ..utils import read_local_state, get_global_state
from ..contract_strings import algofi_manager_strings as manager_strings
from ..contract_strings import algofi_market_strings as market_strings

class Asset:

    def __init__(self, indexer_client: IndexerClient, underlying_asset_id, bank_asset_id, oracle_app_id=None, oracle_price_field=None, oracle_price_scale_factor=None):
        """Constructor me.

        :param indexer_client: a :class:`IndexerClient` for interacting with the network
        :type indexer_client: :class:`IndexerClient`
        :param underlying_asset_id: underlying asset id
        :type int
        :param bank_asset_id: bank asset id
        :type int
        :param oracle_app_id: price oracle app id
        :type int
        :param oracle_price_field: price oracle price field
        :type string
        :param oracle_price_scale_factor: price oracle scale factor to dollars
        :type int
        """

        self.indexer = indexer_client

        # asset info
        self.underlying_asset_id = underlying_asset_id
        self.bank_asset_id = bank_asset_id

        try:
            underlying_asset_info = self.indexer.asset_info(underlying_asset_id).get("asset",{})
        except:
            raise Exception("Asset with id " + str(underlying_asset_id) + " does not exist.")

        try:
            bank_asset_info = self.indexer.asset_info(bank_asset_id).get("asset",{})
        except:
            raise Exception("Asset with id " + str(bank_asset_id) + " does not exist.")

        self.underlying_asset_info = underlying_asset_info["params"] if underlying_asset_id != 1 else {"decimals":6}
        self.bank_asset_info = bank_asset_info["params"]
        
        # oracle info
        if oracle_app_id != None:
            assert oracle_price_field != None
            assert oracle_price_scale_factor != None
        self.oracle_app_id = oracle_app_id
        self.oracle_price_field = oracle_price_field
        self.oracle_price_scale_factor = oracle_price_scale_factor

    def get_underlying_asset_id(self):
        """Returns underying asset id

        :return: underlying asset id
        :rtype: int
        """
        return self.underlying_asset_id
    
    def get_underlying_asset_info(self):
        """Returns underying asset info

        :return: underlying asset info
        :rtype: dict
        """
        return self.underlying_asset_info
    
    def get_bank_asset_id(self):
        """Returns bank asset id

        :return: bank asset id
        :rtype: int
        """
        return self.bank_asset_id
    
    def get_bank_asset_info(self):
        """Returns bank asset info

        :return: bank asset info
        :rtype: dict
        """
        return self.bank_asset_info

    def get_oracle_app_id(self):
        """Returns oracle app id

        :return: oracle app id
        :rtype: int
        """
        return self.oracle_app_id
    
    def get_oracle_price_field(self):
        """Returns oracle price field

        :return: oracle price field
        :rtype: string
        """
        return self.oracle_price_field
    
    def get_oracle_price_scale_factor(self):
        """Returns oracle price scale factor

        :return: oracle price scale factor
        :rtype: int
        """
        return self.oracle_price_scale_factor
    
    def get_raw_price(self):
        """Returns the current raw oracle price

        :return: oracle price
        :rtype: int
        """
        if self.oracle_app_id == None:
            raise Exception("no oracle app id for asset")
        return get_global_state(self.indexer, self.oracle_app_id)[self.oracle_price_field]
    
    def get_underlying_decimals(self):
        """Returns decimals of asset

        :return: decimals
        :rtype: int
        """
        return self.underlying_asset_info['decimals']
    
    def get_price(self):
        """Returns the current oracle price

        :return: oracle price
        :rtype: int
        """
        if self.oracle_app_id == None:
            raise Exception("no oracle app id for asset")
        raw_price = self.get_raw_price()
        return float((raw_price * 10**self.get_underlying_decimals()) / (self.get_oracle_price_scale_factor() * 1e3))
    
    def to_usd(self, amount):
        """Return the usd value of the underlying amount (base units)
        
        :param amount: integer amount of base underlying units
        :type amount: int
        :return: usd value
        :rtype: float
        """
        price = self.get_price()
        return float(amount * price / (10**self.get_underlying_decimals()))

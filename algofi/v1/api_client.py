class ApiClient:
    def __init__(self, algod_client, indexer_client, historical_indexer_client, use_indexer=True):
        self.algod = algod_client
        self.indexer = indexer_client
        self.historical_indexer = historical_indexer_client
        self.use_indexer = use_indexer

    def account_info (self, address, round_num=None):
        if self.use_indexer or round_num:
            indexer_client = self.historical_indexer if round_num else self.indexer
            account_info = indexer_client.account_info(address).get("account", {})
        else:
            account_info = self.algod.account_info(address)

        return account_info

    def application_info (self, app_id, round_num=None):
        if self.use_indexer or round_num:
            indexer_client = self.historical_indexer if round_num else self.indexer
            app_info = indexer_client.applications(app_id).get("application", {})
        else:
            app_info = self.algod.application_info(app_id)

        return app_info

    def asset_info (self, asset_id):
        if self.use_indexer:
            asset_info = self.indexer.asset_info(asset_id).get("asset",{})['params']
        else:
            asset_info = self.algod.asset_info(asset_id)["params"]

        return asset_info

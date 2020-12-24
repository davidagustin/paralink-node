import json
import typing

import aiohttp
import asyncpg

from web3 import Web3
from sanic.log import logger


from src.config import Config
from src.pql.handlers.handler import Handler
from src.pql.exceptions import MethodNotFound, ExternalError, ArgumentError


class EthHandler(Handler):
    """EthHandler handles ETH node requests."""

    URL = "https://api.etherscan.io/api"

    @staticmethod
    async def execute(step: dict) -> typing.Any:
        method = step["method"].split(".")[-1]

        # Connect to W3
        w3 = Web3()
        if not w3.isConnected():
            raise ExternalError(
                "Could not connect to Ethereum node, check WEB3_PROVIDER_URI in .env file."
            )

        if method == "balance":
            EthHandler.require_params(step, ["address"])

            if "params" in step:
                EthHandler.require_params(step["params"], ["block"])
                block = step["params"]["block"]
            else:
                block = "latest"

            try:
                logger.info(
                    f"Obtaining balance for address {step['address']} (block: {block})"
                )
                return w3.eth.getBalance(step["address"], block_identifier=block)
            except Exception as e:
                raise ExternalError(f"{str(type(e))}: {e.args[0]}")

        elif method == "function":
            EthHandler.require_params(step, ["address", "params"])
            EthHandler.require_params(step["params"], ["function", "args"])

            # Parse params
            params = step["params"]
            args = params["args"]
            block = params["block"] if "block" in params else "latest"

            # Get contract ABI from Etherscan API
            data_abi = await EthHandler.fetch_from_explorer(step["address"], "getabi")
            contract_abi = json.loads(data_abi["result"].strip())

            # Create contract object and find function
            con = w3.eth.contract(address=step["address"], abi=contract_abi)

            try:
                fun = con.get_function_by_signature(params["function"])

                logger.info(
                    f"Calling function {fun} on contract address {step['address']} (block: {block})"
                )
                return fun(*args).call(block_identifier=block)
            except Exception as e:
                raise ExternalError(f"{str(type(e))}: {e.args[0]}")
        else:
            raise MethodNotFound(f'handler for SQL method "{method}" not found.')

    @staticmethod
    async def fetch_from_explorer(address: str, action: str) -> typing.Dict:
        """fetch_from_explorer extracts contract ABI from the given address.

        Args:
            address (str): contract address
            action (str): Etherscan API action

        Returns:
            Dict: JSON response from Etherscan API
        """
        params = {
            "module": "contract",
            "action": action,
            "address": address,
            "apiKey": Config().ETHERSCAN_KEY,
        }

        # Check for existence of ETHERSCAN_KEY
        if not params["apiKey"]:
            raise ExternalError("ETHERSCAN_KEY was not supplied in .env file")

        logger.debug(f"Fetching source of {address}")
        async with aiohttp.ClientSession() as session:
            async with session.get(EthHandler.URL, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise ExternalError(
                        f"Etherscan API returned status {resp.status} when querying {action}: {text}"
                    )

                data = await resp.json()
                if int(data["status"]) != 1:
                    raise ExternalError(
                        f"Failed to retrieve data from Etherscan API: {data['result']}"
                    )

                return data

import asyncio
import json
import logging
import os

from yaml import Loader as YamlLoader
from yaml import load as load_yaml

from papiea.client import EntityCRUD
from papiea.core import Action, Entity, Key, ProceduralExecutionStrategy, S2S_Key, Spec
from papiea.python_sdk import ProviderSdk

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


PAPIEA_URL = os.getenv("PAPIEA_URL", "http://127.0.0.1:3333")
PAPIEA_ADMIN_S2S_KEY = os.getenv("PAPIEA_ADMIN_S2S_KEY", "")
PROVIDER_HOST = os.getenv("PROVIDER_HOST", "")
PROVIDER_PORT = int(os.getenv("PROVIDER_PORT", "9000"))
PROVIDER_PREFIX = "griffon"
PROVIDER_VERSION = "0.1.0"
PROVIDER_ADMIN_S2S_KEY = "Sa8xaic9"


def wait_port_is_open(url):
    import socket
    import time
    from urllib.parse import urlparse

    urlparts = urlparse(url).netloc.split(":")
    host = urlparts[0]
    port = int(urlparts[1])
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return
        except socket.gaierror:
            pass
        time.sleep(1)


def load_yaml_from_file(filename):
    with open(filename) as f:
        return load_yaml(f, Loader=YamlLoader)


async def create_provider_admin_s2s_key(sdk: ProviderSdk, new_key: Key):
    admin_security_api = sdk.provider_security_api

    the_key = S2S_Key(
        name="Griffon provider admin s2s key",
        owner="sarabjit.saini@nutanix.com",
        key=new_key,
        user_info={"is_provider_admin": True},
    )

    keys = await admin_security_api.list_keys()
    for key in keys:
        if key.name == the_key.name:
            logger.debug(f"Key {the_key.name} already exists")
            return

    new_s2s_key = await admin_security_api.create_key(the_key)
    provider_admin_security_api = sdk.new_security_api(new_key)
    user_info = await provider_admin_security_api.user_info()
    logger.debug(f"User info {user_info}")


async def create_user_s2s_key(sdk: ProviderSdk):
    admin_security_api = sdk.provider_security_api

    the_key = S2S_Key(
        name="Griffon provider some.user s2s key",
        user_info={"owner": "nutanix", "tenant": "ada14b27-c147-4aca-9b9f-7762f1f48426"},
    )

    new_s2s_key = await admin_security_api.create_key(the_key)
    user_security_api = sdk.new_security_api(new_s2s_key.key)
    user_info = await user_security_api.user_info()
    logger.debug(f"User info {user_info}")
    return new_s2s_key.key


async def image_node(ctx, entity, config):
    logger.debug(f"image_node() input config:\n%s" % config)
    """
    WIP: Add implementation to image node and track node state machine
    """
    entity.spec.state = "imaged"
    allowed = await ctx.check_permission([(Action.Update, entity.metadata)])
    logger.debug(f"Allowed {allowed}")
    if not allowed:
        raise Exception("Permission denied")
    async with ctx.entity_client_for_user(entity.metadata) as entity_client:
        await entity_client.update(entity.metadata, entity.spec)
    return entity.spec.state

async def main():
    # Load kinds
    node_kind = load_yaml_from_file("./kinds/node.yml")
    meta_ext = load_yaml_from_file("./griffon_metadata_extension.yml")
    proceedure_image_node_in = load_yaml_from_file("./kinds/image_node.yml")
    procedure_image_node_out = load_yaml_from_file("./kinds/image_node_out.yml")

    # Set auth
    oauth_config = load_yaml_from_file("./policy/griffon_auth.yaml")
    with open("./policy/griffon_model.txt") as f:
        casbin_model = f.read()
    with open("./policy/griffon_policy.txt") as f:
        casbin_initial_policy = f.read()

    # Create Griffon provider
    async with ProviderSdk.create_provider(
        PAPIEA_URL, PAPIEA_ADMIN_S2S_KEY, PROVIDER_HOST, PROVIDER_PORT
    ) as sdk:
        sdk.version(PROVIDER_VERSION)
        sdk.prefix(PROVIDER_PREFIX)
        sdk.secure_with(
            oauth_config=oauth_config,
            casbin_model=casbin_model,
            casbin_initial_policy=casbin_initial_policy,
        )
        sdk.metadata_extension(meta_ext)
        await create_provider_admin_s2s_key(sdk, PROVIDER_ADMIN_S2S_KEY)

        node = sdk.new_kind(node_kind)
        # Register image_node procedure
        node.entity_procedure(
            "image_node",
            ProceduralExecutionStrategy.HaltIntentful,
            proceedure_image_node_in,
            procedure_image_node_out,
            image_node,
        )
        """
        # Register reboot_to_target procedure
        node.entity_procedure(
            "reboot_to_target",
            ProceduralExecutionStrategy.HaltIntentful,
            proceedure_reboot_to_target_in,
            procedure_reboot_to_target_out,
            reboot_to_target,
        )
        """
        await sdk.register()
        server = sdk.server

        user_s2s_key = await create_user_s2s_key(sdk)
        async with EntityCRUD(
            PAPIEA_URL, PROVIDER_PREFIX, PROVIDER_VERSION, "node", user_s2s_key
        ) as entity_client:
            entity = await entity_client.create(
                Spec(ip="172.26.1.5", state="free"),
                metadata_extension={
                    "owner": "nutanix",
                    "tenant_uuid": "ada14b27-c147-4aca-9b9f-7762f1f48426",
                },
            )
            logger.debug(f"Created entity {entity}")
            request = ""
            with open('./config/node_172.26.1.5.json', 'r') as f:
              request = json.load(f)
            logger.debug(f"Image_node config: %s" % request)
            res = await entity_client.invoke_procedure("image_node",
                                                       entity.metadata,
                                                       request)
            logger.debug(f"Procedure returns {res}")
            entity = await entity_client.get(entity.metadata)
            logger.debug(f"Updated entity {res}")

        while True:
            # Serve provider procedures forever
            await asyncio.sleep(300)

        await server.close()


if __name__ == "__main__":
    wait_port_is_open(PAPIEA_URL)
    asyncio.run(main())

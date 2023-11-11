import os

import hydra

import flows
from flows.flow_launchers import FlowLauncher
from flows.backends.api_info import ApiInfo
from flows.utils.general_helpers import read_yaml_file
from flows import logging
from flows.flow_cache import CACHING_PARAMETERS, clear_cache

CACHING_PARAMETERS.do_caching = False  # Set to True in order to disable caching
# clear_cache() # Uncomment this line to clear the cache

logging.set_verbosity_debug()
logging.auto_set_dir()

dependencies = [
    {"url": "aiflows/ControllerExecutorFlowModule", "revision": "67f65d607df0f9e78db666c75c2129c1a708abd0"},
    {"url": "aiflows/HumanStandardInputFlowModule", "revision": "890e92da1fefbae642fd84296e31bca7f61ea710"},
    {"url": "aiflows/LCToolFlowModule", "revision": "46dd24ecc3dc4f4f0191e57c202cc7d20e8e7782"},
]
from flows import flow_verse

flow_verse.sync_dependencies(dependencies)
from ReActWithHumanFeedback import ReActWithHumanFeedback

if __name__ == "__main__":
    # ~~~ Set the API information ~~~
    # OpenAI backend
    api_information = [ApiInfo(backend_used="openai",
                              api_key = os.getenv("OPENAI_API_KEY"))]
    # Azure backend
    # api_information = ApiInfo(backend_used = "azure",
    #                           api_base = os.getenv("AZURE_API_BASE"),
    #                           api_key = os.getenv("AZURE_OPENAI_KEY"),
    #                           api_version =  os.getenv("AZURE_API_VERSION") )

    path_to_output_file = None
    # path_to_output_file = "output.jsonl"  # Uncomment this line to save the output to disk
    root_dir = "examples/ReActWithHumanFeedback"
    cfg_path = os.path.join(root_dir, "ReActWithHumanFeedback.yaml")
    cfg = read_yaml_file(cfg_path)
    cfg["subflows_config"]["Controller"]["backend"]["api_infos"] = api_information
    flow = ReActWithHumanFeedback.instantiate_from_default_config(**cfg)
    
    # ~~~ Instantiate the Flow ~~~
    flow_with_interfaces = {
        "flow": flow,
        "input_interface": (
            None
            if cfg.get("input_interface", None) is None
            else hydra.utils.instantiate(cfg['input_interface'], _recursive_=False)
        ),
        "output_interface": (
            None
            if cfg.get("output_interface", None) is None
            else hydra.utils.instantiate(cfg['output_interface'], _recursive_=False)
        ),
    }

    # ~~~ Get the data ~~~
    # This can be a list of samples
    # data = {"id": 0, "goal": "Answer the following question: What is the population of Canada?"}  # Uses wikipedia
    # data = {"id": 0, "goal": "Answer the following question: Who was the NBA champion in 2023?"}  # Uses duckduckgo
    data = {"id": 0, "goal": "Answer the following question: What is the profession and date of birth of Michael Jordan?"}
    # At first, we retrieve information about Michael Jordan the basketball player
    # If we provide feedback, only in the first round, that we are not interested in the basketball player,
    #   but the statistician, and skip the feedback in the next rounds, we get the correct answer

    # ~~~ Run inference ~~~
    path_to_output_file = None
    # path_to_output_file = "output.jsonl"  # Uncomment this line to save the output to disk

    _, outputs = FlowLauncher.launch(
        flow_with_interfaces=flow_with_interfaces,
        data=data,
        path_to_output_file=path_to_output_file,
    )

    # ~~~ Print the output ~~~
    flow_output_data = outputs[0]
    print(flow_output_data)

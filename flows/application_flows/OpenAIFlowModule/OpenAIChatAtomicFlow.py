from copy import deepcopy

import hydra

import time

from typing import List, Dict, Optional, Any, Tuple

from flows.flow_launchers.api_info import ApiInfo
from langchain import PromptTemplate
import langchain
from langchain.schema import HumanMessage, AIMessage, SystemMessage

from flows.base_flows import AtomicFlow
from flows.datasets import GenericDemonstrationsDataset

from flows.utils import logging
from flows.messages.flow_message import UpdateMessage_ChatMessage

log = logging.get_logger(__name__)


# ToDo: Add support for demonstrations


class OpenAIChatAtomicFlow(AtomicFlow):
    REQUIRED_KEYS_CONFIG = ["model_name", "generation_parameters"]

    SUPPORTS_CACHING: bool = True

    system_message_prompt_template: PromptTemplate
    human_message_prompt_template: PromptTemplate

    init_human_message_prompt_template: Optional[PromptTemplate] = None
    demonstrations: GenericDemonstrationsDataset = None
    demonstrations_k: Optional[int] = None
    demonstrations_response_prompt_template: PromptTemplate = None

    def __init__(self,
                 system_message_prompt_template,
                 human_message_prompt_template,
                 init_human_message_prompt_template,
                 demonstrations_response_prompt_template=None,
                 demonstrations=None,
                 **kwargs):
        super().__init__(**kwargs)
        self.system_message_prompt_template = system_message_prompt_template
        self.human_message_prompt_template = human_message_prompt_template
        self.init_human_message_prompt_template = init_human_message_prompt_template
        self.demonstrations_response_prompt_template = demonstrations_response_prompt_template
        self.demonstrations = demonstrations
        self.demonstrations_k = self.flow_config.get("demonstrations_k", None)

        assert self.flow_config["name"] not in [
            "system",
            "user",
            "assistant",
        ], f"Flow name '{self.flow_config['name']}' cannot be 'system', 'user' or 'assistant'"

    def set_up_flow_state(self):
        super().set_up_flow_state()
        self.flow_state["previous_messages"] = []

    @classmethod
    def _set_up_prompts(cls, config):
        kwargs = {}

        kwargs["system_message_prompt_template"] = \
            hydra.utils.instantiate(config['system_message_prompt_template'], _convert_="partial")
        kwargs["init_human_message_prompt_template"] = \
            hydra.utils.instantiate(config['init_human_message_prompt_template'], _convert_="partial")
        kwargs["human_message_prompt_template"] = \
            hydra.utils.instantiate(config['human_message_prompt_template'], _convert_="partial")

        if "demonstrations_response_prompt_template" in config:
            kwargs["demonstrations_response_prompt_template"] = \
                hydra.utils.instantiate(config['demonstrations_response_prompt_template'], _convert_="partial")
            kwargs["demonstrations"] = GenericDemonstrationsDataset(**config['demonstrations'])

        return kwargs

    @classmethod
    def instantiate_from_config(cls, config):
        flow_config = deepcopy(config)

        kwargs = {"flow_config": flow_config}
        # kwargs["output_data_transformations"] = cls._set_up_data_transformations(config["output_data_transformations"])

        # ~~~ Set up prompts ~~~
        kwargs.update(cls._set_up_prompts(flow_config))

        # ~~~ Instantiate flow ~~~
        return cls(**kwargs)

    def _is_conversation_initialized(self):
        if len(self.flow_state["previous_messages"]) > 0:
            return True

        return False

    def get_interface_description(self):
        if self._is_conversation_initialized():

            return {"input": self.flow_config["input_interface_initialized"],
                    "output": self.flow_config["output_interface"]}
        else:
            return {"input": self.flow_config["input_interface_non_initialized"],
                    "output": self.flow_config["output_interface"]}

    @staticmethod
    def _get_message(prompt_template, input_data: Dict[str, Any]):
        template_kwargs = {}
        for input_variable in prompt_template.input_variables:
            template_kwargs[input_variable] = input_data[input_variable]

        msg_content = prompt_template.format(**template_kwargs)
        return msg_content

    def _get_demonstration_query_message_content(self, sample_data: Dict):
        input_variables = self.init_human_message_prompt_template.input_variables
        return self.init_human_message_prompt_template.format(**{k: sample_data[k] for k in input_variables})

    def _get_demonstration_response_message_content(self, sample_data: Dict):
        input_variables = self.demonstrations_response_prompt_template.input_variables
        return self.demonstrations_response_prompt_template.format(**{k: sample_data[k] for k in input_variables})

    def _add_demonstrations(self):
        if self.demonstrations is not None:
            demonstrations = self.demonstrations

            c = 0
            for example in demonstrations:
                if self.demonstrations_k is not None and c >= self.demonstrations_k:
                    break
                c += 1
                query = self._get_demonstration_query_message_content(example)
                response = self._get_demonstration_response_message_content(example)

                self._state_update_add_chat_message(content=query,
                                                    role=self.flow_config["user_name"])

                self._state_update_add_chat_message(content=response,
                                                    role=self.flow_config["assistant_name"])

    def _state_update_add_chat_message(self,
                                       role: str,
                                       content: str) -> None:

        # Add the message to the previous messages list
        if role == self.flow_config["system_name"]:
            self.flow_state["previous_messages"].append(SystemMessage(content=content))
        elif role == self.flow_config["user_name"]:
            self.flow_state["previous_messages"].append(HumanMessage(content=content))
        elif role == self.flow_config["assistant_name"]:
            self.flow_state["previous_messages"].append(AIMessage(content=content))
        else:
            raise Exception(f"Invalid role: `{role}`.\n"
                            f"Role should be one of: "
                            f"`{self.flow_config['system_name']}`, "
                            f"`{self.flow_config['user_name']}`, "
                            f"`{self.flow_config['assistant_name']}`")

        # Log the update to the flow messages list
        chat_message = UpdateMessage_ChatMessage(
            created_by=self.flow_config["name"],
            updated_flow=self.flow_config["name"],
            role=role,
            content=content,
        )
        self._log_message(chat_message)

    def _find_api_info(self, backend_used, api_information):
        for api in api_information:
            if api.backend_used == backend_used:
                return api
        return None

    def _call(self):
        backend_used = self._get_from_state("backend_used")
        api_information = self._get_from_state("api_information")
        api = self._find_api_info(backend_used, api_information)
        assert api is not None, f"specified backend_used: {0} not found in api information".format(backend_used)
        api_key = api.api_key

        if backend_used == 'azure':
            from langchain.chat_models import AzureChatOpenAI
            endpoint = api.endpoint
            backend = AzureChatOpenAI(
                openai_api_type='azure',
                openai_api_key=api_key,
                openai_api_base=endpoint,
                openai_api_version='2023-05-15',
                deployment_name='gpt-35-turbo',
                **self.flow_config["generation_parameters"],
            )

        elif backend_used == 'openai':
            backend = langchain.chat_models.ChatOpenAI(
                model_name=self.flow_config["model_name"],
                openai_api_key=api_key,
                **self.flow_config["generation_parameters"],
            )
        else:
            raise ValueError(f"Unsupported backend: {backend_used}")

        # import openai
        #
        # if openai.api_type == "azure":
        #     backend = langchain.chat_models.ChatOpenAI(
        #         engine=self.flow_config["model_name"],
        #         openai_api_key=api_key,
        #         **self.flow_config["generation_parameters"],
        #     )
        # else:

        messages = self.flow_state["previous_messages"]

        _success = False
        attempts = 1
        error = None
        response = None
        while attempts <= self.flow_config['n_api_retries']:
            try:
                response = backend(messages).content
                _success = True
                break
            except Exception as e:
                log.error(
                    f"Error {attempts} in calling backend: {e}. Key used: `{api_key}`. "
                    f"Retrying in {self.flow_config['wait_time_between_retries']} seconds..."
                )
                # log.error(
                #     f"The API call raised an exception with the following arguments: "
                #     f"\n{self.flow_state['history'].to_string()}"
                # ) # ToDo: Make this message more user-friendly
                attempts += 1
                time.sleep(self.flow_config['wait_time_between_retries'])
                error = e

        if not _success:
            raise error

        return response

    def _initialize_conversation(self, input_data: Dict[str, Any]):
        # ~~~ Add the system message ~~~
        system_message_content = self._get_message(self.system_message_prompt_template, input_data)

        self._state_update_add_chat_message(content=system_message_content,
                                            role=self.flow_config["system_name"])

        # # ~~~ Add the demonstration query-response tuples (if any) ~~~
        self._add_demonstrations()

    def _process_input(self, input_data: Dict[str, Any]):
        if self._is_conversation_initialized():
            # Construct the message using the human message prompt template
            user_message_content = self._get_message(self.human_message_prompt_template, input_data)

        else:
            # Initialize the conversation (add the system message, and potentially the demonstrations)
            self._initialize_conversation(input_data)
            if getattr(self, "init_human_message_prompt_template", None) is not None:
                # Construct the message using the query message prompt template
                user_message_content = self._get_message(self.init_human_message_prompt_template, input_data)
            else:
                user_message_content = self._get_message(self.human_message_prompt_template, input_data)

        self._state_update_add_chat_message(role=self.flow_config["user_name"],
                                            content=user_message_content)

    def run(self,
            input_data: Dict[str, Any]) -> Dict[str, Any]:
        # ~~~ Process input ~~~
        self._process_input(input_data)

        # ~~~ Call ~~~
        response = self._call()
        self._state_update_add_chat_message(
            role=self.flow_config["assistant_name"],
            content=response
        )

        return {"api_output": response}

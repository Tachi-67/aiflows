"""

"""
import os
import sys
import copy
from abc import ABC
from typing import List, Dict, Any, Union, Optional

import hydra
from omegaconf import OmegaConf
from ..utils import logging
from flows.history import FlowHistory
from flows.messages import Message, InputMessage, UpdateMessage_Generic, \
    UpdateMessage_NamespaceReset, UpdateMessage_FullReset, \
    OutputMessage
from flows.utils.general_helpers import recursive_dictionary_update, nested_keys_search, process_config_leafs
from flows.utils.rich_utils import print_config_tree
from flows.flow_cache import FlowCache, CachingKey, CachingValue, CACHING_PARAMETERS

log = logging.get_logger(__name__)


class Flow(ABC):
    """
    Abstract class for all flows.
    """
    # user should at least provide `REQUIRED_KEYS_CONFIG` when instantiate a flow
    REQUIRED_KEYS_CONFIG = ["name", "description"]

    SUPPORTS_CACHING = False

    flow_config: Dict[str, Any]
    flow_state: Dict[str, Any]
    history: FlowHistory

    # below parameters are essential for flow instantiation, but we provide value for them,
    # so user is not required to provide them in the flow config
    __default_flow_config = {
        "name": "Flow",
        "description": "A flow",
        "private_keys": ["api_keys"],
        "keys_to_ignore_for_hash": ["api_keys", "name", "description", "api_information"],
        "clear_flow_namespace_on_run_end": True,
        "keep_raw_response": True,
        "enable_cache": False,  # whether to enable cache for this flow
    }

    def __init__(
            self,
            flow_config: Dict[str, Any],
    ):
        """
        __init__ should not be called directly be a user. Instead, use the classmethod `instantiate_from_config` or `instantiate_from_default_config`
        """
        self.flow_config = flow_config
        self.cache = FlowCache()
        self._validate_flow_config(flow_config)

        self.set_up_flow_state()

        if log.getEffectiveLevel() == logging.DEBUG:
            log.debug(
                f"Flow {self.flow_config.get('name', 'unknown_name')} instantiated with the following parameters:")
            print_config_tree(self.flow_config)

    @property
    def name(self):
        return self.flow_config["name"]
    
    @classmethod
    def instantiate_from_default_config(cls, **overrides: Optional[Dict[str, Any]]):
        """
        This method is called by the FlowLauncher to build the flow.
        """
        if overrides is None:
            overrides = {}

        config = cls.get_config(**overrides)

        return cls.instantiate_from_config(config)

    @classmethod
    def _validate_flow_config(cls, flow_config: Dict[str, Any]):
        if not hasattr(cls, "REQUIRED_KEYS_CONFIG"):
            raise ValueError("REQUIRED_KEYS_CONFIG should be defined for each Flow class.")

        for key in cls.REQUIRED_KEYS_CONFIG:
            if key not in flow_config:
                raise ValueError(f"{key} is a required parameter in the flow_config.")

    @classmethod
    def get_config(cls, **overrides):
        """
        Returns the default config for the flow, with the overrides applied.

        The default implementation construct the default config by recursively merging the configs of the base classes.
        """
        if cls == Flow:
            return copy.deepcopy(cls.__default_flow_config)
        elif cls == ABC:
            return {}
        elif cls == object:
            return {}

        # ~~~ Recursively retrieve and merge the configs of the base classes to construct the default config ~~~
        super_cls = cls.__base__
        parent_default_config = super_cls.get_config()

        path_to_flow_directory = os.path.dirname(sys.modules[cls.__module__].__file__)
        class_name = cls.__name__

        path_to_config = os.path.join(path_to_flow_directory, f"{class_name}.yaml")
        if os.path.exists(path_to_config):
            default_config = OmegaConf.to_container(
                OmegaConf.load(path_to_config),
                resolve=True
            )

            cls_parent_module = ".".join(cls.__module__.split(".")[:-1])
            
            process_config_leafs(default_config, 
                               lambda k, v: 
                               (cls_parent_module + v  if k == "_target_" and v.startswith(".") else v))

            config = recursive_dictionary_update(parent_default_config, default_config)

        # TODO(yeeef): ugly fix, figure out why only this works
        elif hasattr(cls,
                     f"_{cls.__name__}__default_flow_config"):  # no yaml but __default_flow_config exists in class declaration
            # log.warn(f'{cls.__name__}, {cls.__default_flow_config}, {getattr(cls, f"_{cls.__name__}__default_flow_config")}')
            config = recursive_dictionary_update(parent_default_config,
                                                 copy.deepcopy(getattr(cls, f"_{cls.__name__}__default_flow_config")))
        else:
            config = parent_default_config
            log.debug(f"Flow config not found at {path_to_config}.")

        # ~~~~ Apply the overrides ~~~~
        config = recursive_dictionary_update(config, overrides)

        # return cls.config_class(**overrides)
        return config

    @classmethod
    def instantiate_from_config(cls, config):
        kwargs = {"flow_config": copy.deepcopy(config)}
        return cls(**kwargs)

    @classmethod
    def instantiate_with_overrides(cls, overrides):
        config = cls.get_config(**overrides)
        return cls.instantiate_from_config(config)

    def set_up_flow_state(self):
        self.flow_state = {}
        self.history = FlowHistory()

    def reset(self,
              full_reset: bool,
              recursive: bool,
              src_flow: Optional[Union["Flow", str]] = "Launcher"):
        """
        Reset the flow state and history. If recursive is True, reset all subflows as well.

        :param full_reset:  If True, remove all data in flow_state. If False, keep the data in flow_state.
        :param recursive:
        :param src_flow:
        :return:
        """

        if isinstance(src_flow, Flow):
            src_flow = src_flow.flow_config["name"]

        if recursive and hasattr(self, "subflows"):
            for _, flow in self.subflows.items():
                flow.reset(full_reset=full_reset, recursive=True)

        if full_reset:
            message = UpdateMessage_FullReset(
                created_by=src_flow,
                updated_flow=self.flow_config["name"],
                keys_deleted_from_namespace=[]
            )
            self._log_message(message)
            self.set_up_flow_state()  # resets the flow state
        else:
            message = UpdateMessage_NamespaceReset(
                created_by=src_flow,
                updated_flow=self.flow_config["name"],
                keys_deleted_from_namespace=[]
            )
            self._log_message(message)

    def _get_from_state(self, key: str, default: Any = None):
        return self.flow_state.get(key, default)

    def _state_update_dict(self, update_data: Union[Dict[str, Any], Message]):
        """
        Updates the flow state with the key-value pairs in a data dictionary (or message.data if a message is passed).
        """
        if isinstance(update_data, Message):
            update_data = update_data.data["output_data"]  # TODO(yeeef): error-prone

        if len(update_data) == 0:
            raise ValueError("The state_update_dict was called with an empty dictionary. If there is a justified "
                             "reason to allow this, please replace the ValueError with a log.warning, and make a PR")

        updates = {}
        for key, value in update_data.items():
            if key in self.flow_state:
                if value is None or value == self.flow_state[key]:
                    continue

            updates[key] = value
            self.flow_state[key] = copy.deepcopy(value)

        if len(updates) != 0:
            state_update_message = UpdateMessage_Generic(
                created_by=self.flow_config['name'],
                updated_flow=self.flow_config["name"],
                data=updates,
            )
            return self._log_message(state_update_message)

    def __getstate__(self):
        """Used by the caching mechanism such that the flow can be returned to the same state using the cache"""
        return {
            "flow_config": self.flow_config,
            "flow_state": self.flow_state,
        }

    def __setstate__(self, state):
        """Used by the caching mechanism to skip computation that has already been done and stored in the cache"""
        self.flow_config = state["flow_config"]
        self.flow_state = state["flow_state"]

    def __repr__(self):
        """Generates the string that will be used by the hashing function"""
        # ToDo(https://github.com/epfl-dlab/flows/issues/60): Document how this and the caching works (that all args should implement __repr__, should be applied only to atomic flows etc.)
        # ~~~ This is the string that will be used by the hashing ~~~
        # ~~~ It keeps the config (self.flow_config) and the state (flow_state) ignoring some predefined keys ~~~
        config_hashing_params = {k: v for k, v in self.flow_config.items() if k not in self.flow_config["keys_to_ignore_for_hash"]}
        state_hashing_params = {k: v for k, v in self.flow_state.items() if k not in self.flow_config["keys_to_ignore_for_hash"]}
        hash_dict = {"flow_config": config_hashing_params, "flow_state": state_hashing_params}
        return repr(hash_dict)

    # ToDo(https://github.com/epfl-dlab/flows/issues/60): Move the repr logic here and update the hashing function to use this instead
    # def get_hash_string(self):
    #     raise NotImplementedError()

    def get_interface_description(self):
        return {"input": self.flow_config["input_interface"], "output": self.flow_config["output_interface"]}

    def _log_message(self, message: Message):
        log.debug(message.to_string())
        return self.history.add_message(message)

    def _fetch_state_attributes_by_keys(self,
                                        keys: Union[List[str], None],
                                        allow_class_attributes: bool = False):  # TODO(yeeef): remove this parameter
        data = {}

        if keys is None:
            # Return all available data
            for key in self.flow_state:
                data[key] = self.flow_state[key]

            if allow_class_attributes:
                for key in self.__dict__:
                    if key in data:
                        log.warning(f"Data key {key} present in both in the flow state and the class namespace.")
                        continue
                    data[key] = self.__dict__[key]

            return data
        
        for key in keys:
            value, found = nested_keys_search(self.flow_state, key)

            if found:
                data[key] = value
            elif allow_class_attributes and key in self.__dict__:
                data[key] = self.__dict__[key]
            else:
                raise KeyError(f"Key {key} not found in the flow state or the class namespace.")    
        return data
    
    def _package_input_message(
            self,
            payload: Dict[str, Any],
            dst_flow: "Flow",
            api_keys: Optional[Dict[str, str]] = None,
    ):
        private_keys = dst_flow.flow_config["private_keys"]
        keys_to_ignore_for_hash = dst_flow.flow_config["keys_to_ignore_for_hash"]

        src_flow = self.flow_config["name"]
        if isinstance(dst_flow, Flow):
            dst_flow = dst_flow.flow_config["name"]

        assert len(set(["src_flow", "dst_flow"]).intersection(set(payload.keys()))) == 0, \
            "The keys 'src_flow' and 'dst_flow' are special keys and cannot be used in the data dictionary"
        
        # ~~~ Create the message ~~~
        msg = InputMessage(
            data_dict=copy.deepcopy(payload),
            private_keys=private_keys,
            keys_to_ignore_for_hash=keys_to_ignore_for_hash,
            src_flow=src_flow,
            dst_flow=dst_flow,
            api_keys=api_keys,
            created_by=self.name,
        )
        return msg
    
    def _package_output_message(
            self,
            input_message: InputMessage,
            response: Dict[str, Any],
            raw_response: Dict[str, Any]
    ):
        output_data = copy.deepcopy(response)

        return OutputMessage(
            created_by=self.flow_config['name'],
            src_flow=self.flow_config['name'],
            dst_flow=input_message.src_flow,
            # output_keys=self.get_output_keys(),
            # missing_output_keys=[],
            output_data=output_data,
            raw_response=raw_response,
            input_message_id=input_message.message_id,
            history=self.history,
        )

    def run(self,
            input_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def __get_from_cache(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        assert self.flow_config["enable_cache"] and CACHING_PARAMETERS.do_caching

        if not self.SUPPORTS_CACHING:
            raise Exception(
                f"Flow {self.flow_config['name']} does not support caching, but flow_config['enable_cache'] is True")

        # ~~~ get the hash string ~~~
        keys_to_ignore_for_hash = self.flow_config["keys_to_ignore_for_hash"]
        input_data_to_hash = {k: v for k, v in input_data.items() if k not in keys_to_ignore_for_hash}
        cache_key_hash = CachingKey(self, input_data_to_hash, keys_to_ignore_for_hash).hash_string()
        # ~~~ get from cache ~~~
        response = None
        cached_value: CachingValue = self.cache.get(cache_key_hash)
        if cached_value is not None:
            # Retrieve output from cache
            response = cached_value.output_results

            # Restore the flow to the state it was in when the output was created
            self.__setstate__(cached_value.full_state)

            # Restore the history messages
            for message in cached_value.history_messages_created:
                message_softcopy = message  # ToDo: Get a softcopy with an updated timestamp
                self._log_message(message_softcopy)

            log.debug(f"Retrieved from cache: {self.__class__.__name__} "
                      f"-- (input_data.keys()={list(input_data_to_hash.keys())}, "
                      f"keys_to_ignore_for_hash={keys_to_ignore_for_hash})")
            log.debug(f"Retrieved from cache: {str(cached_value)}")

        else:
            # Call the original function
            history_len_pre_execution = len(self.history)

            # Execute the call
            response = self.run(input_data)

            # Retrieve the messages created during the execution
            num_created_messages = len(self.history) - history_len_pre_execution
            new_history_messages = self.history.get_last_n_messages(num_created_messages)

            value_to_cache = CachingValue(
                output_results=response,
                full_state=self.__getstate__(),
                history_messages_created=new_history_messages
            )

            self.cache.set(cache_key_hash, value_to_cache)
            log.debug(f"Cached key: f{cache_key_hash}")
            # log.debug(f"Cached: {str(value_to_cache)} \n"
            #           f"-- (input_data.keys()={list(input_data_to_hash.keys())}, "
            #           f"keys_to_ignore_for_hash={keys_to_ignore_for_hash})")

        return response

    def __call__(self, input_message: InputMessage):
        # # sanity check input_data
        # assert set(input_message.data.keys()) == set(self.get_input_keys()), \
        #     (input_message.data.keys(), self.get_input_keys())

        # set api_keys in flow_state
        # new: set api_information (api keys, endpoints) in flow_state
        if input_message.api_information:
            self._state_update_dict(
                {"api_information": input_message.api_information}
            )
        if input_message.backend_used:
            self._state_update_dict(
                {"backend_used": input_message.backend_used}
            )

    
        # ~~~ check and log input ~~~
        self._log_message(input_message)

        # ~~~ Execute the logic of the flow ~~~
        if not self.flow_config["enable_cache"] or not CACHING_PARAMETERS.do_caching:
            response = self.run(input_message.data)
        else:
            response = self.__get_from_cache(input_message.data)

        # if not self.flow_config["keep_raw_response"]:
        #     raw_response = None
        # else:
        #     raw_response = copy.deepcopy(response)

        # ToDo: Decide whether to keep "output_parsers" on the Flow (not the interface level)
        # response = self._apply_data_transformations(response,
        #                                             self.output_data_transformations,
        #                                             self.get_output_keys())
        # response = {k: v for k, v in response.items() if k in self.get_output_keys()}

        # sanity check
        # we don't tolerate missing keys, as `get_output_keys`` should be aware of the current flow state
        # assert set(response.keys()) == set(self.get_output_keys()), \
        #     (response.keys(), self.get_output_keys())
        
        # ~~~ Package output message ~~~
        output_message = self._package_output_message(
            input_message=input_message,
            response=response,
            raw_response=None,
        )

        self._post_call_hook()

        return output_message

    def _post_call_hook(self):
        """Removes all attributes from the namespace that are not in self.KEYS_TO_IGNORE_WHEN_RESETTING_NAMESPACE"""
        if self.flow_config['clear_flow_namespace_on_run_end']:
            self.reset(full_reset=False, recursive=False, src_flow=self)

    def __str__(self):
        return self._to_string()

    def _to_string(self, indent_level=0):
        """Generates a string representation of the flow"""
        indent = "\t" * indent_level
        name = self.flow_config.get("name", "unnamed")
        description = self.flow_config.get("description", "no description")
        input_keys = self.flow_config.get("input_keys", "no input keys")
        output_keys = self.flow_config.get("output_keys", "no output keys")
        class_name = self.__class__.__name__

        entries = [
            f"{indent}Name: {name}",
            f"{indent}Class name: {class_name}",
            f"{indent}Type: {self.type()}",
            f"{indent}Description: {description}",
            f"{indent}Input keys: {input_keys}",
            f"{indent}Output keys: {output_keys}",
        ]
        return "\n".join(entries) + "\n"

    @classmethod
    def type(cls):
        raise NotImplementedError

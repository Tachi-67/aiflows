from typing import List, Dict

from src.flows import CompositeFlow, Flow
from src.messages import InputMessage
from src import utils

log = utils.get_pylogger(__name__)


class SequentialFlow(CompositeFlow):
    def __init__(
            self,
            name: str,
            description: str,
            expected_inputs: List[str],
            expected_outputs: List[str],
            flows: Dict[str, Flow],
            early_exit_key: str = None,
            verbose: bool = False
    ):
        super().__init__(
            name=name,
            description=description,
            expected_inputs=expected_inputs,
            expected_outputs=expected_outputs,
            flows=flows,
            verbose=verbose
        )

        assert len(flows) > 0, f"Sequential flow needs at least one flow, currently has {len(flows)}"

        self.ordered_flows = list(self.flows.keys())
        self.early_exit_key = early_exit_key

    def _early_exit(self):
        if self.early_exit_key:
            if self.early_exit_key in self.state:
                return bool(self.state[self.early_exit_key].content)
        return False

    def _flow(self, input_message: InputMessage, expected_outputs: List[str]):
        _parents = [input_message.message_id]
        for current_flow_id in self.ordered_flows:
            current_flow = self.flows[current_flow_id]

            current_flow.initialize(api_key=self.state["api_key"].content)
            flow_answer = self._call_flow(flow_id=current_flow_id, parents=_parents)
            self._read_answer_update_state(flow_answer)

            if self._early_exit():
                log.info("Early end of sequential flow detected")
                break

            _parents = [flow_answer.message_id]

        parsed_outputs = {k: self.state[k] for k in expected_outputs}

        return parsed_outputs

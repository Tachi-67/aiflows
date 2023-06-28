import pytest

from flows.base_flows import SequentialFlow, AtomicFlow
from tests.mocks import MockFlow

def atomic_flow_builder(bias):
    class MyFlow(AtomicFlow):
        def run(self, input_data, output_keys):
            answer = self.flow_config["bias"]
            for k, v in input_data.items():
                answer += v
            return {self.output_keys[0]: answer}

    return MyFlow(
        name="my-flow",
        description="flow-sum",
        output_keys=["v0"],
        input_keys=["v0"],
        bias=bias
    )


def test_basic_instantiating() -> None:
    with pytest.raises(KeyError):
        SequentialFlow()

    with pytest.raises(Exception):
        SequentialFlow(name="name", description="description")

    flow_a = atomic_flow_builder(10)
    flow_b = atomic_flow_builder(1)

    flow = SequentialFlow(
        name="name",
        description="description",
        input_keys=["v0"],
        verbose=False,
        dry_run=True,
        flows=[flow_a, flow_b]
    )

    assert not flow.verbose
    assert flow.dry_run
    assert len(flow.flow_config["flows"]) == 2
    assert isinstance(flow.flow_config["flows"][0], AtomicFlow)
    assert isinstance(flow.flow_config["flows"][1], AtomicFlow)


def test_basic_call():
    flow_a = atomic_flow_builder(bias=2)
    flow_b = atomic_flow_builder(bias=4)

    seq_flow = SequentialFlow(
        name="name",
        description="description",
        input_keys=["v0"],
        output_keys=["v0"],
        dry_run=False,
        max_rounds=3,
        eoi_key=None,
        max_round=2,
        flows=[flow_a, flow_b]
    )

    data = {"v0": 10}
    task_message = seq_flow.package_task_message(
        recipient_flow=seq_flow,
        task_name="task",
        task_data=data,
        output_keys=["v0"]
    )

    answer = seq_flow(task_message)
    assert answer.data["v0"] == 16

def test_early_exit(monkeypatch, caplog):

    flow_a = atomic_flow_builder(bias=2)
    flow_b = atomic_flow_builder(bias=4)

    seq_flow = SequentialFlow(
        name="name",
        description="description",
        input_keys=["v0"],
        output_keys=["v0"],
        dry_run=False,
        max_rounds=3,
        eoi_key=None,
        max_round=2,
        flows=[flow_a, flow_b]
    )

    data = {"v0": 10}
    task_message = seq_flow.package_task_message(
        recipient_flow=seq_flow,
        task_name="task",
        task_data=data,
        output_keys=[]
    )
    seq_flow.early_exit_key="early_exit"
    seq_flow.flow_state["early_exit"] = True

    with caplog.at_level("INFO"):
        _ = seq_flow(task_message)
    assert caplog.records[-1].message == "Early end of sequential flow detected"


    seq_flow = SequentialFlow(
        name="name",
        description="description",
        input_keys=["v0"],
        output_keys=["v0"],
        dry_run=False,
        max_rounds=3,
        eoi_key=None,
        max_round=2,
        flows=[flow_a, flow_b]
    )

    data = {"v0": 10}
    task_message = seq_flow.package_task_message(
        recipient_flow=seq_flow,
        task_name="task",
        task_data=data,
        output_keys=[]
    )
    seq_flow.early_exit_key="early_exit"
    seq_flow.early_exit = True

    with caplog.at_level("INFO"):
        _ = seq_flow(task_message)
    assert caplog.records[-1].message == "Early end of sequential flow detected"

def test_pass_on_api_key():
    flow_a = MockFlow()
    flow_b = MockFlow()

    seq_flow = SequentialFlow(
        name="name",
        description="description",
        input_keys=["v0"],
        output_keys=["v0"],
        dry_run=False,
        max_rounds=3,
        eoi_key=None,
        max_round=2,
        flows=[flow_a, flow_b]
    )

    data = {"v0": 10}
    task_message = seq_flow.package_task_message(
        recipient_flow=seq_flow,
        task_name="task",
        task_data=data,
        output_keys=["v0", "mock_flow_api_key"]
    )

    seq_flow.set_api_key("api_key")

    answer = seq_flow(task_message)
    assert answer.data["mock_flow_api_key"] == "api_key"
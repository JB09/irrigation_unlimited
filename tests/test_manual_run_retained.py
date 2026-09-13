"""irrigation_unlimited queued manual run retention tester"""

import homeassistant.core as ha
from custom_components.irrigation_unlimited.const import (
    SERVICE_LOAD_SCHEDULE,
    SERVICE_MANUAL_RUN,
    SERVICE_TIME_ADJUST,
)
from tests.iu_test_support import IUExam

IUExam.quiet_mode()

SEQUENCE = "binary_sensor.irrigation_unlimited_c1_s1"
ZONE = "binary_sensor.irrigation_unlimited_c1_z1"


async def queue_two_manual_runs(exam: IUExam) -> None:
    """Start one manual run and queue a second behind it"""
    for _ in range(2):
        await exam.call(
            SERVICE_MANUAL_RUN,
            {"entity_id": SEQUENCE, "time": "0:04:00", "queue": True},
        )


# pylint: disable=unused-argument
async def test_manual_run_retained(
    hass: ha.HomeAssistant, skip_dependencies, skip_history
):
    """A service call which only rebuilds the scheduled runs must leave a
    queued manual run alone. A manual run is not derived from a schedule so
    clearing it discards it for good"""

    async with IUExam(hass, "manual_run_retained.yaml") as exam:

        await exam.begin_test(1)
        await queue_two_manual_runs(exam)
        await exam.finish_test()

        await exam.begin_test(2)
        await queue_two_manual_runs(exam)
        await exam.call(SERVICE_TIME_ADJUST, {"entity_id": SEQUENCE, "percentage": 50})
        sequence = exam.coordinator.controllers[0].sequences[0]
        assert sum(1 for sqr in sequence.runs if sqr.is_manual()) == 2
        await exam.finish_test()

        await exam.begin_test(3)
        # Drop test 2's adjustment so this case stands on its own
        await exam.call(SERVICE_TIME_ADJUST, {"entity_id": SEQUENCE, "reset": None})
        await queue_two_manual_runs(exam)
        await exam.call(
            SERVICE_LOAD_SCHEDULE, {"schedule_id": "morning", "time": "06:30"}
        )
        sequence = exam.coordinator.controllers[0].sequences[0]
        assert sum(1 for sqr in sequence.runs if sqr.is_manual()) == 2
        await exam.finish_test()

        await exam.begin_test(4)
        # Put test 3's schedule back so this case stands on its own
        await exam.call(
            SERVICE_LOAD_SCHEDULE, {"schedule_id": "morning", "time": "06:00"}
        )
        await queue_two_manual_runs(exam)
        # A zone adjustment does not change which zones take part in the run,
        # so the built manual runs stay valid
        await exam.call(SERVICE_TIME_ADJUST, {"entity_id": ZONE, "percentage": 50})
        sequence = exam.coordinator.controllers[0].sequences[0]
        assert sum(1 for sqr in sequence.runs if sqr.is_manual()) == 2
        await exam.finish_test()

        exam.check_summary()

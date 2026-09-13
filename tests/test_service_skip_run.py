"""irrigation_unlimited service skip_run tester"""

import json
from unittest.mock import patch
import pytest
import homeassistant.core as ha
from homeassistant.helpers.restore_state import RestoreEntity
from custom_components.irrigation_unlimited.const import (
    SERVICE_MANUAL_RUN,
    SERVICE_SKIP_RUN,
)
from tests.iu_test_support import IUExam, mk_local, mk_utc

IUExam.quiet_mode()

SEQUENCE = "binary_sensor.irrigation_unlimited_c1_s1"
CONTROLLER = "binary_sensor.irrigation_unlimited_c1_m"


# pylint: disable=unused-argument
async def test_service_skip_run(
    hass: ha.HomeAssistant, skip_dependencies, skip_history
):
    """Test the skip_run service call. The next scheduled run is dropped
    but the schedule itself is left alone"""

    async with IUExam(hass, "service_skip_run.yaml") as exam:

        await exam.begin_test(1)
        await exam.finish_test()

        await exam.begin_test(2)
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE})
        await exam.finish_test()

        await exam.begin_test(3)
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": CONTROLLER, "sequence_id": 1})
        await exam.finish_test()

        await exam.begin_test(4)
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE, "count": 2})
        await exam.finish_test()

        await exam.begin_test(5)
        await exam.call(
            SERVICE_SKIP_RUN,
            {"entity_id": SEQUENCE, "until": "2021-01-04 13:00"},
        )
        await exam.finish_test()

        await exam.begin_test(6)
        await exam.run_until("2021-01-04 06:05")
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE})
        await exam.finish_test()

        await exam.begin_test(7)
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE})
        await exam.run_until("2021-01-04 05:30")
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE, "reset": None})
        await exam.finish_test()

        await exam.begin_test(8)
        await exam.call(
            SERVICE_MANUAL_RUN,
            {"entity_id": SEQUENCE, "time": "0:04:00", "delay": "0:10:00"},
        )
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE})
        await exam.finish_test()

        await exam.begin_test(9)
        await exam.call(SERVICE_SKIP_RUN, {"entity_id": CONTROLLER})
        await exam.finish_test()

        # future_span only builds 3 days ahead, until reaches past that
        await exam.begin_test(10)
        await exam.call(
            SERVICE_SKIP_RUN,
            {"entity_id": SEQUENCE, "until": "2021-01-08 13:00"},
        )
        await exam.finish_test()

        exam.check_summary()


# pylint: disable=unused-argument
async def test_service_skip_run_state(
    hass: ha.HomeAssistant, skip_dependencies, skip_history
):
    """Check the sequence state exposed by the skip_run service call"""

    async with IUExam(hass, "service_skip_run.yaml") as exam:
        exam.no_check()

        await exam.begin_test(1)
        sequence = exam.coordinator.controllers[0].sequences[0]

        assert sequence.skipped == []
        assert sequence.skip_until is None
        assert hass.states.get(SEQUENCE).attributes["next_start"] == mk_local(
            "2021-01-04 06:00"
        )

        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE})
        assert sequence.skipped == [mk_local("2021-01-04 06:00")]
        assert hass.states.get(SEQUENCE).attributes["skipped"] == [
            mk_local("2021-01-04 06:00")
        ]
        assert hass.states.get(SEQUENCE).attributes["next_start"] == mk_local(
            "2021-01-04 12:00"
        )

        # The record is dropped once the run it waived can no longer be built
        await exam.run_until("2021-01-04 06:11")
        assert sequence.skipped == []
        assert hass.states.get(SEQUENCE).attributes["next_start"] == mk_local(
            "2021-01-04 12:00"
        )

        await exam.finish_test()

        await exam.begin_test(1)
        sequence = exam.coordinator.controllers[0].sequences[0]

        await exam.call(
            SERVICE_SKIP_RUN,
            {"entity_id": SEQUENCE, "until": "2021-01-04 13:00"},
        )
        assert sequence.skip_until == mk_local("2021-01-04 13:00")
        assert sequence.skipped == [
            mk_local("2021-01-04 06:00"),
            mk_local("2021-01-04 12:00"),
        ]
        assert hass.states.get(SEQUENCE).attributes["skip_until"] == mk_local(
            "2021-01-04 13:00"
        )
        assert hass.states.get(SEQUENCE).attributes["next_start"] == mk_local(
            "2021-01-05 06:00"
        )

        await exam.call(SERVICE_SKIP_RUN, {"entity_id": SEQUENCE, "reset": None})
        assert sequence.skipped == []
        assert sequence.skip_until is None
        assert hass.states.get(SEQUENCE).attributes["next_start"] == mk_local(
            "2021-01-04 06:00"
        )

        await exam.finish_test()


@pytest.fixture(name="mock_state_skipped")
def mock_state_skipped():
    """Patch HA with a sequence which waived its 06:00 run before the
    restart. Attributes come back as ISO strings out of the state machine"""

    def func(self):
        entity: RestoreEntity = self
        if entity.entity_id == SEQUENCE:
            return ha.State(
                entity.entity_id,
                "off",
                {"skipped": [mk_local("2021-01-04 06:00").isoformat()]},
                mk_utc("2021-01-04 06:03:00"),
            )
        return None

    with patch(
        "homeassistant.helpers.restore_state.RestoreEntity.async_get_last_state",
        autospec=True,
    ) as mock:
        mock.side_effect = func
        yield


@pytest.fixture(name="mock_state_skipped_coordinator")
def mock_state_skipped_coordinator():
    """Patch HA with the coordinator style restore data"""
    with patch(
        "homeassistant.helpers.restore_state.RestoreEntity.async_get_last_state"
    ) as mock:
        configuration = json.dumps(
            {
                "controllers": [
                    {
                        "index": 0,
                        "sequences": [
                            {
                                "index": 0,
                                "skipped": [mk_local("2021-01-04 06:00").isoformat()],
                                "skip_until": None,
                            }
                        ],
                    }
                ]
            }
        )
        mock.return_value = ha.State(
            "irrigation_unlimited.coordinator",
            "ok",
            {"configuration": configuration},
            mk_utc("2021-01-04 06:03:00"),
        )
        yield


# pylint: disable=unused-argument, redefined-outer-name
async def test_service_skip_run_restore_entity(
    hass: ha.HomeAssistant, skip_dependencies, skip_history, mock_state_skipped
):
    """A restart inside the window of a waived run must not resurrect it.
    Without the restored record the run would restart late and truncated"""

    async with IUExam(hass, "service_skip_run_restore.yaml") as exam:
        sequence = exam.coordinator.controllers[0].sequences[0]
        assert sequence.skipped == [mk_local("2021-01-04 06:00")]

        await exam.begin_test(1)
        await exam.finish_test()
        exam.check_summary()


# pylint: disable=unused-argument, redefined-outer-name
async def test_service_skip_run_restore_coordinator(
    hass: ha.HomeAssistant,
    skip_dependencies,
    skip_history,
    mock_state_skipped_coordinator,
):
    """As above but restoring from the coordinator entity"""

    async with IUExam(hass, "service_skip_run_restore_coordinator.yaml") as exam:
        sequence = exam.coordinator.controllers[0].sequences[0]
        assert sequence.skipped == [mk_local("2021-01-04 06:00")]

        await exam.begin_test(1)
        await exam.finish_test()
        exam.check_summary()

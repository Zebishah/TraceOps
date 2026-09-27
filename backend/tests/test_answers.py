from ops_pilot.services.answers import get_used_source_numbers


def test_get_used_source_numbers() -> None:
    answer = (
        "Fact one [SOURCE 1]. Another fact [SOURCE 4]. Again [SOURCE 1]. Final fact [SOURCE 2]."
    )

    assert get_used_source_numbers(answer) == [1, 4, 2]

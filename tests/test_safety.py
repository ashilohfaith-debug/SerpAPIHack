"""P2 safety: risk classification, confirmation strength, protected fields."""

from relay.safety import (
    Action,
    ConfirmationStrength,
    PermissionEngine,
    Risk,
    is_protected_field,
)

E = PermissionEngine()


def test_readonly_is_safe():
    for kind in ("read_screen", "observe", "scroll", "narrate", "list_elements"):
        d = E.classify(Action(kind=kind))
        assert d.risk is Risk.SAFE and not d.requires_confirmation


def test_blocked_actions_refused():
    d = E.classify(Action(kind="solve_captcha"))
    assert d.risk is Risk.BLOCKED and d.allowed is False


def test_danger_labelled_target_is_elevated_phrase():
    d = E.classify(Action(kind="click", target_label="Delete", target_app="Files"))
    assert d.risk is Risk.ELEVATED
    assert d.confirmation is ConfirmationStrength.PHRASE
    assert "can't be undone" in d.spoken_summary


def test_high_risk_kind_requires_keyboard_confirm():
    d = E.classify(Action(kind="purchase", target_label="Buy now", target_app="Shop"))
    assert d.risk is Risk.ELEVATED
    assert d.confirmation is ConfirmationStrength.KEYBOARD  # not a bare spoken yes


def test_unidentified_click_defaults_to_confirm():
    d = E.classify(Action(kind="click", target_label="", target_app="App"))
    assert d.risk is Risk.CONFIRM
    assert d.confirmation is ConfirmationStrength.SIMPLE


def test_routine_identified_mutation_is_caution_narrate():
    d = E.classify(Action(kind="click", target_label="OK", target_app="Dialog"))
    assert d.risk is Risk.CAUTION
    assert d.confirmation is ConfirmationStrength.NARRATE


def test_typing_not_judged_by_content():
    # typing the word "delete" is not dangerous; only a control labelled Delete is
    d = E.classify(Action(kind="type", text="please delete everything", target_label="Body"))
    assert d.risk is Risk.CAUTION


def test_reversible_mutation_runs_without_confirm():
    d = E.classify(Action(kind="move_file", reversible=True))
    assert d.risk is Risk.REVERSIBLE and not d.requires_confirmation


def test_protected_field_detection():
    assert is_protected_field(role="Edit", name="Password")
    assert is_protected_field(is_password_field=True)
    assert is_protected_field(name="One-time code")
    assert not is_protected_field(role="Edit", name="Search")

"""The passcode gate, from jay-withers/appkit (`appkit.passcode`).

A shared passcode rather than Entra sign-in, the same trade as gym-log and
finances: Container Apps' built-in auth needs the `azapi` provider that no repo
in this estate uses, in exchange for an Entra round trip to look at a career
profile. This is reachable from the public internet the moment ingress is
external, so the gate defaults **on** and a missing passcode fails closed.
appkit's module docstring has the rest of the reasoning.
"""

from __future__ import annotations

from appkit.passcode import PasscodeGate

from ..settings import secret, settings

COOKIE_NAME = "career_session"

gate = PasscodeGate(COOKIE_NAME, settings=settings, secret=secret)

issue = gate.issue
valid = gate.valid
check_passcode = gate.check_passcode
require_session = gate.require_session

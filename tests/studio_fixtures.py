"""The couriers policy with a document whose sentences its rules came from, for the studio's tests."""
from conftest import load

from policyproof.authoring.document import parse
from policyproof.authoring.extraction import Extraction, Link

TEXT = ("# Couriers policy\n\nWhat courier customers get.\n\n## Couriers\n\n- Courier parcels are never refunded.\n"
        "- A late courier parcel is refunded if the customer asks. Lost parcels are always refunded.\n\n"
        "## Post\n\nPost parcels that aren't lost are not refunded. Days late are never negative.\n")
DOC = parse(TEXT)
INTRO, S4, S5, S6, S10, S9 = (s.anchor for s in DOC.sentences)
POLICY = load("defects/couriers.yaml")
EXTRACTION = Extraction(POLICY, (Link("C4", S4), Link("C5", S5), Link("C6", S6), Link("C10", S10), Link("C9", S9)),
                        (INTRO,))

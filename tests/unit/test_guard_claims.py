from policyproof.core.check import Claim
from policyproof.core.syntax import Cmp, EnumLit, IntLit, Not, Var
from policyproof.guards.claims import check
from policyproof.guards.raw import RawClaim, Rejected

REPLY = "It came by courier, 3 days late, so you get a refund and not a voucher."


def test_claims_that_decode_and_quote_the_reply_are_kept(toy):
    kept, rejected = check(toy, REPLY, (RawClaim({"eq": ["carrier", "COURIER"]}, "by courier"),
                                        RawClaim({"eq": ["daysLate", 3]}, "3 days late"),
                                        RawClaim({"not": "voucher"}, "not a voucher")))
    assert kept == (Claim(Cmp("eq", Var("carrier"), EnumLit("Carrier", "COURIER")), "by courier"),
                    Claim(Cmp("eq", Var("daysLate"), IntLit(3)), "3 days late"),
                    Claim(Not(Var("voucher")), "not a voucher"))
    assert rejected == ()


def test_bad_claims_are_rejected_with_a_reason(toy):
    kept, rejected = check(toy, REPLY, (
        RawClaim({"eq": ["carrier", "TRUCK"]}, "by courier"),    # unknown name
        RawClaim("daysLate", "3 days late"),                     # not a statement (Int)
        RawClaim(True, "you get a refund"),                      # mentions no variable
        RawClaim("refund", "a full refund today"),               # quote not in the reply
    ))
    assert kept == ()
    assert [r.item for r in rejected] == ["by courier", "3 days late", "you get a refund", "a full refund today"]
    assert "unknown name 'TRUCK'" in rejected[0].reason
    assert rejected[1] == Rejected("3 days late", "not a true/false statement")
    assert rejected[2] == Rejected("you get a refund", "mentions no policy variable")
    assert rejected[3] == Rejected("a full refund today", "quote not in reply")

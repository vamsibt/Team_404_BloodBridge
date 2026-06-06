from sqlalchemy.orm import Session
from app import models


def get_current_turn_donor(db: Session, bridge_id: str):
    assignment = (
        db.query(models.BridgeAssignment)
        .filter(
            models.BridgeAssignment.bridge_id == bridge_id,
            models.BridgeAssignment.donor_type == models.BridgeType.bridge,
            models.BridgeAssignment.current_turn == True,
        )
        .first()
    )
    return assignment.donor if assignment else None


def advance_bridge_turn(db: Session, bridge_id: str) -> int | None:
    assignments = (
        db.query(models.BridgeAssignment)
        .filter(
            models.BridgeAssignment.bridge_id == bridge_id,
            models.BridgeAssignment.donor_type == models.BridgeType.bridge,
        )
        .order_by(models.BridgeAssignment.slot_order)
        .all()
    )
    if not assignments:
        return None
    current_idx = next((i for i, a in enumerate(assignments) if a.current_turn), 0)
    assignments[current_idx].current_turn = False
    next_idx = (current_idx + 1) % len(assignments)
    assignments[next_idx].current_turn = True
    return assignments[next_idx].slot_order

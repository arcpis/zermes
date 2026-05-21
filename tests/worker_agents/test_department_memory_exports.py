from worker_agents import (
    DEPARTMENT_MEMORY_SCHEMA_VERSION,
    DepartmentMemoryKind,
    DepartmentMemoryProposal,
    DepartmentMemoryProposalStore,
    DepartmentMemoryReadRequest,
    DepartmentMemoryReadService,
    DepartmentMemoryRecord,
    DepartmentMemoryReviewAction,
    DepartmentMemoryReviewDecision,
    DepartmentMemoryReviewService,
    DepartmentMemoryReviewerRole,
    DepartmentMemorySensitivity,
    DepartmentMemoryVisibility,
    department_memory_to_dict,
    proposal_from_private_asset_input,
)


def test_department_memory_exports_are_available_from_package():
    assert DEPARTMENT_MEMORY_SCHEMA_VERSION == 1
    assert DepartmentMemoryKind.RISK.value == "risk"
    assert DepartmentMemoryVisibility.INHERITABLE_SUMMARY.value == (
        "inheritable_summary"
    )
    assert DepartmentMemorySensitivity.LOW.value == "low"
    assert DepartmentMemoryProposal.__name__ == "DepartmentMemoryProposal"
    assert DepartmentMemoryRecord.__name__ == "DepartmentMemoryRecord"
    assert DepartmentMemoryProposalStore.__name__ == "DepartmentMemoryProposalStore"
    assert DepartmentMemoryReviewAction.__name__ == "DepartmentMemoryReviewAction"
    assert DepartmentMemoryReviewDecision.APPROVE.value == "approve"
    assert DepartmentMemoryReviewerRole.MAIN_AGENT.value == "main_agent"
    assert DepartmentMemoryReviewService.__name__ == "DepartmentMemoryReviewService"
    assert DepartmentMemoryReadRequest.__name__ == "DepartmentMemoryReadRequest"
    assert DepartmentMemoryReadService.__name__ == "DepartmentMemoryReadService"
    assert department_memory_to_dict.__name__ == "department_memory_to_dict"
    assert proposal_from_private_asset_input.__name__ == (
        "proposal_from_private_asset_input"
    )

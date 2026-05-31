from worker_agents.department_skills import (
    DepartmentSkillBindingProposal,
    DepartmentSkillBindingState,
    DepartmentSkillBindingStore,
    DepartmentSkillBindingVisibility,
    DepartmentSkillProposalAction,
    DepartmentSkillReviewAction,
    DepartmentSkillReviewDecision,
    DepartmentSkillReviewService,
    DepartmentSkillReviewerRole,
    resolve_department_skill_bindings,
)


def _approve_binding(
    store,
    *,
    department_id,
    proposal_id,
    skill_id,
    state,
    visibility=DepartmentSkillBindingVisibility.PRIVATE_TO_DEPARTMENT,
):
    proposal = DepartmentSkillBindingProposal(
        proposal_id=proposal_id,
        department_id=department_id,
        proposed_action=DepartmentSkillProposalAction.ADD_BINDING,
        skill_id=skill_id,
        candidate_state=state,
        visibility=visibility,
        candidate_guidance=f"Use {skill_id} for matching tasks.",
        source_actor="main_agent",
    )
    store.create_proposal(proposal)
    return DepartmentSkillReviewService(store).approve(
        department_id,
        proposal_id,
        DepartmentSkillReviewAction(
            proposal_id=proposal_id,
            decision=DepartmentSkillReviewDecision.APPROVE,
            actor_id="lead-worker",
            actor_role=DepartmentSkillReviewerRole.DEPARTMENT_LEAD,
            reason="Useful department guidance.",
            reviewed_at="2026-05-21T01:00:00Z",
        ),
    )


def test_resolve_inherits_only_public_guidance(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    _approve_binding(
        store,
        department_id="parent",
        proposal_id="private-binding",
        skill_id="private_review",
        state=DepartmentSkillBindingState.DEFAULT,
    )
    _approve_binding(
        store,
        department_id="parent",
        proposal_id="public-binding",
        skill_id="release_review",
        state=DepartmentSkillBindingState.DEFAULT,
        visibility=DepartmentSkillBindingVisibility.INHERITABLE_GUIDANCE,
    )

    resolved = resolve_department_skill_bindings(
        store,
        "child",
        inherited_department_ids=("parent",),
    )

    assert [item.binding.skill_id for item in resolved] == ["release_review"]
    assert resolved[0].inherited is True


def test_local_restricted_binding_overrides_inherited_default(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    _approve_binding(
        store,
        department_id="parent",
        proposal_id="parent-default",
        skill_id="release_review",
        state=DepartmentSkillBindingState.DEFAULT,
        visibility=DepartmentSkillBindingVisibility.INHERITABLE_GUIDANCE,
    )
    _approve_binding(
        store,
        department_id="child",
        proposal_id="child-restricted",
        skill_id="release_review",
        state=DepartmentSkillBindingState.RESTRICTED,
    )

    resolved = resolve_department_skill_bindings(
        store,
        "child",
        inherited_department_ids=("parent",),
    )

    assert len(resolved) == 1
    assert resolved[0].binding.state == DepartmentSkillBindingState.RESTRICTED
    assert resolved[0].inherited is False


def test_disabled_binding_is_more_conservative_than_recommended(tmp_path):
    store = DepartmentSkillBindingStore(root=tmp_path)
    _approve_binding(
        store,
        department_id="parent",
        proposal_id="parent-recommended",
        skill_id="release_review",
        state=DepartmentSkillBindingState.RECOMMENDED,
        visibility=DepartmentSkillBindingVisibility.INHERITABLE_GUIDANCE,
    )
    _approve_binding(
        store,
        department_id="child",
        proposal_id="child-disabled",
        skill_id="release_review",
        state=DepartmentSkillBindingState.DISABLED,
    )

    resolved = resolve_department_skill_bindings(
        store,
        "child",
        inherited_department_ids=("parent",),
    )

    assert resolved[0].binding.state == DepartmentSkillBindingState.DISABLED

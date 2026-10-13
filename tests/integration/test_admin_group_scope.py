"""HTTP regressions for full group scope, identity changes, and bulk preflight."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.integration.admin_scope_support import (
    ADMIN, ROOT, CONSUMER_ADMIN, MEMBER_A, MEMBER_B, PROJECT_A, PROJECT_B,
    AUTH, directory, router_client, session_for,
)

pytestmark = pytest.mark.usefixtures('patched_db_error_logger')
UG = 'src.routes.admin_user_groups'
PG = 'src.routes.admin_project_groups'
BULK = 'src.routes.bulk_operations'


def group(hash, name=None):
    return SimpleNamespace(id=hash, group_hash=hash, group_name=name or hash,
        group_description=None, description=None, created_at=datetime.now(timezone.utc), updated_at=None)


UA, UB, UM, UE = (group(name) for name in ('ug-A', 'ug-B', 'ug-mixed', 'ug-empty'))
PA, PB, PM = (group(name) for name in ('pg-A', 'pg-B', 'pg-mixed'))
GROUPS = {g.group_hash: g for g in (UA, UB, UM, UE, PA, PB, PM)}
FOOTPRINTS = {UA.id: {'prj-A'}, UB.id: {'prj-B'}, UM.id: {'prj-A', 'prj-B'},
              UE.id: set(), PA.id: {'prj-A'}, PB.id: {'prj-B'}, PM.id: {'prj-A', 'prj-B'}}


@pytest.mark.parametrize('kind,operation', [('user', 'typo'), ('project', 'bulk_assign'), ('unknown', 'read')])
def test_unknown_authorization_operations_fail_closed(kind, operation):
    from src.Util.admin_group_scope import group_authorization
    with pytest.raises(ValueError, match='Unknown'):
        group_authorization(kind, operation)


def seams():
    writer = MagicMock(return_value={'granted': True})
    create = MagicMock(return_value=UA)
    mutations = {
        'assign_user_to_user_group': MagicMock(return_value=True),
        'remove_user_from_user_group': MagicMock(return_value=True),
        'grant_user_group_project_group_access': writer,
        'revoke_user_group_project_group_access': MagicMock(return_value=True),
        'delete_user_group': MagicMock(return_value=True),
        'update_user_group': MagicMock(return_value=UA),
        'create_user_group': create,
    }
    extra = [(f'{UG}.{name}', mock) for name, mock in mutations.items()]
    for module in (UG, PG):
        extra.extend([
            (f'{module}.get_{"user" if module == UG else "project"}_group_by_hash',
             MagicMock(side_effect=lambda h: GROUPS.get(h))),
        ])
    extra.extend([
        (f'{UG}.get_project_group_by_hash', MagicMock(side_effect=lambda h: GROUPS.get(h))),
        (f'{UG}.get_users_in_group', MagicMock(return_value=[MEMBER_A, MEMBER_B, ROOT])),
        (f'{UG}.get_projects_for_user_group', MagicMock(return_value=[])),
        (f'{UG}.get_project_groups_for_user_group', MagicMock(return_value=[])),
        (f'{UG}.get_user_groups_for_user', MagicMock(return_value=[UA, UB, UM, UE])),
        (f'{UG}.revoke_project_sessions_losing_access', MagicMock()),
        ('src.Util.admin_group_scope.group_project_ids',
         MagicMock(side_effect=lambda kind, id: frozenset(FOOTPRINTS[id]))),
        (f'{PG}.assign_project_to_group', MagicMock(return_value=True)),
        (f'{PG}.create_project_group', MagicMock(return_value=PA)),
        (f'{PG}.update_project_group', MagicMock(return_value=PA)),
        (f'{BULK}.get_user_group_by_name', MagicMock(side_effect=lambda name: GROUPS.get(name))),
        (f'{BULK}.bulk_add_users_to_group', MagicMock(return_value={'success_count': 1, 'error_count': 0, 'results': [], 'errors': []})),
    ])
    return mutations, extra


@pytest.mark.parametrize('path,data,writer', [
    ('/admin/user-groups/ug-A/project-groups', {'project_group_hash': 'pg-B'}, 'grant_user_group_project_group_access'),
    ('/admin/user-groups/ug-mixed/members', {'user_hash': MEMBER_A.user_hash}, 'assign_user_to_user_group'),
    ('/admin/user-groups/ug-B/members', {'user_hash': MEMBER_A.user_hash}, 'assign_user_to_user_group'),
    ('/admin/user-groups/ug-empty/members', {'user_hash': MEMBER_A.user_hash}, 'assign_user_to_user_group'),
    ('/admin/user-groups/ug-A/members', {'user_hash': MEMBER_B.user_hash}, 'assign_user_to_user_group'),
])
async def test_admin_cannot_mutate_foreign_mixed_unbound_or_foreign_users(path, data, writer):
    writes, extra = seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG, PG) as client:
            response = await client.post(path, headers=AUTH, data=data)
    assert response.status_code == 403, response.text
    writes[writer].assert_not_called()


async def test_admin_cannot_attach_foreign_project():
    _, extra = seams()
    assign = dict(extra)[f'{PG}.assign_project_to_group']
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(PG) as client:
            response = await client.post('/admin/project-groups/pg-A/projects', headers=AUTH,
                                         data={'project_hash': PROJECT_B.project_hash})
    assert response.status_code == 403, response.text
    assign.assert_not_called()


@pytest.mark.parametrize('actor', [MEMBER_A, CONSUMER_ADMIN])
@pytest.mark.parametrize('route', ['/admin/user-groups', '/admin/project-groups'])
async def test_consumers_cannot_administer_groups_even_with_reserved_permissions(actor, route):
    with directory(session_for(actor)):
        async with router_client(UG, PG) as client:
            response = await client.get(route, headers=AUTH)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize('route,writer', [('/admin/user-groups', 'create_user_group'),
                                        ('/admin/project-groups', 'create_project_group')])
@pytest.mark.parametrize('project_hash,status', [(None, 400), ('ph-B', 403), ('missing', 404), ('ph-A', 200)])
async def test_creation_requires_assigned_project_and_preserves_empty_group(route, writer, project_hash, status):
    _, extra = seams()
    create = dict(extra)[f'{UG if writer == "create_user_group" else PG}.{writer}']
    data = {'group_name': 'new-team'}
    if project_hash is not None:
        data['project_hash'] = project_hash
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG, PG) as client:
            response = await client.post(route, headers=AUTH, data=data)
    assert response.status_code == status, response.text
    if status == 200:
        assert create.call_args.kwargs['scope_project_id'] == PROJECT_A.id
    else:
        create.assert_not_called()


async def test_root_can_create_unbound_group():
    writes, extra = seams()
    with directory(session_for(ROOT), extra=extra):
        async with router_client(UG) as client:
            response = await client.post('/admin/user-groups', headers=AUTH, data={'group_name': 'global'})
    assert response.status_code == 200, response.text
    assert writes['create_user_group'].call_args.kwargs['scope_project_id'] is None


async def test_non_root_cannot_rebind_group():
    writes, extra = seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG) as client:
            response = await client.put('/admin/user-groups/ug-A', headers=AUTH,
                                        data={'project_hash': 'ph-A', 'description': 'updated'})
    assert response.status_code == 403, response.text
    writes['update_user_group'].assert_not_called()


@pytest.mark.parametrize('route,data', [
    ('/admin/user-groups/ug-A/members/bulk', {'user_hashes': [MEMBER_A.user_hash, MEMBER_B.user_hash]}),
    ('/admin/user-groups/bulk-assign', {'user_hashes': [MEMBER_A.user_hash, MEMBER_B.user_hash], 'group_names': ['ug-A']}),
])
async def test_bulk_authorization_preflight_prevents_partial_writes(route, data):
    writes, extra = seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG, BULK) as client:
            response = await client.post(route, headers=AUTH,
                **({'json': data} if route.endswith('/members/bulk') else {'data': data}))
    assert response.status_code == 403, response.text
    writes['assign_user_to_user_group'].assert_not_called()
    dict(extra)[f'{BULK}.bulk_add_users_to_group'].assert_not_called()


async def test_nested_users_and_user_groups_are_filtered():
    _, extra = seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG) as client:
            members = await client.get('/admin/user-groups/ug-A/members', headers=AUTH)
            groups = await client.get(f'/admin/user-groups/users/{MEMBER_A.user_hash}/groups', headers=AUTH)
    assert members.status_code == groups.status_code == 200
    assert [u['user_hash'] for u in members.json()['members']] == [MEMBER_A.user_hash]
    assert members.json()['pagination']['total'] == 1
    assert [g['group_hash'] for g in groups.json()['groups']] == ['ug-A']


async def test_missing_group_keeps_404():
    _, extra = seams()
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG) as client:
            response = await client.get('/admin/user-groups/missing', headers=AUTH)
    assert response.status_code == 404

@pytest.mark.parametrize('change', ['demotion', 'unassignment'])
async def test_authority_is_resolved_again_inside_mutation_transaction(change):
    writes, extra = seams()
    if change == 'demotion':
        extra.append(('src.Util.db.get_user_type', MagicMock(side_effect=['admin', 'consumer'])))
    else:
        extra.append(('src.Util.db.get_admin_assigned_projects', MagicMock(side_effect=[['prj-A'], []])))
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG) as client:
            response = await client.post('/admin/user-groups/ug-A/members', headers=AUTH,
                                         data={'user_hash': MEMBER_A.user_hash})
    assert response.status_code == 403, response.text
    writes['assign_user_to_user_group'].assert_not_called()


async def test_admin_assigned_to_all_projects_can_manage_shared_group():
    writes, extra = seams()
    extra.append(('src.Util.db.get_admin_assigned_projects', MagicMock(return_value=['prj-A', 'prj-B'])))
    with directory(session_for(ADMIN), extra=extra):
        async with router_client(UG) as client:
            response = await client.post('/admin/user-groups/ug-mixed/members', headers=AUTH,
                                         data={'user_hash': MEMBER_B.user_hash})
    assert response.status_code == 200, response.text
    writes['assign_user_to_user_group'].assert_called_once()

"""Regression tests for revision-bound A2A interruptions (local fixtures only)."""
from copy import deepcopy
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from a2a import A2AInboundAdapter, A2ATaskStore, SQLiteA2ATaskStore, PostgresA2ATaskStore, _task_state
from intent_ir import IntentIR
from runner import RecipeDAGRunner
from telemetry import EventBus, ListSubscriber


def request(revision=1, *, message_id=None, session='session', context='context'):
    return {'message': {'role': 'user', 'messageId': message_id or f'message-{revision}',
                        'contextId': context, 'parts': [{'text': 'Find shoes'}],
                        'metadata': {'sessionId': session, 'intentId': 'intent', 'intentRevision': revision}}}


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    result = A2ATaskStore() if request.param == 'memory' else SQLiteA2ATaskStore(str(tmp_path/'tasks.db'))
    yield result
    if isinstance(result, SQLiteA2ATaskStore):
        result.close()


def adapter(store, executor=lambda *_: {'items': []}, authorization_check=None):
    bus = EventBus(); events = ListSubscriber(); bus.subscribe(events)
    intent = IntentIR(intent_id='compiled', goal='search_catalog', domain='commerce', action='search', object='products', desired_output='json')
    result = A2AInboundAdapter(compiler=SimpleNamespace(compile=lambda _: intent),
        retriever=SimpleNamespace(retrieve=lambda *_args, **_kwargs: [SimpleNamespace(capability_id='search')]),
        capability_by_id=lambda _: SimpleNamespace(id='search', provider='fixture'),
        runner=RecipeDAGRunner(bus=bus), executor=executor, bus=bus, source_endpoint='http://localhost/a2a',
        task_store=store, authorization_check=authorization_check)
    # A positive synthetic verifier makes suppression tests meaningful: absent
    # an interruption, this fixture would otherwise claim completed.
    result._assess_execution = lambda **kw: dict(outcome_id='outcome', evidence_id='evidence',
        verification_id='verification', outcome_status='COMPLETED', verification_status='VERIFIED',
        completion_authoritative=True)
    return result, events


def assert_rejected(task, state):
    assert _task_state(task) == state
    assert task['metadata']['completionAuthoritative'] is False
    assert task['metadata']['resultRejected'] is True
    assert 'verificationStatus' not in task['metadata']
    assert 'completed successfully' not in str(task)
    assert 'secret-result' not in str(task)


def test_late_older_revision_is_discarded(store):
    entered=Event(); release=Event(); output=[]
    def execute(*_):
        if not entered.is_set():
            entered.set(); assert release.wait(3)
        return {'secret-result': 'provider-data'}
    worker, events = adapter(store, execute)
    thread=Thread(target=lambda: output.append(worker.handle(request(1))['task']))
    thread.start()
    try:
        assert entered.wait(3)
        latest=worker.handle(request(2))['task']
        assert _task_state(latest)=='completed'
    finally:
        release.set(); thread.join(3)
    assert not thread.is_alive()
    assert_rejected(output[0], 'failed')
    assert store.get(output[0]['id']) == output[0]
    evaluations=[event for event in events.events if event.event_type.value=='evaluation.completed']
    assert len(evaluations)==1


def test_cancel_during_dispatch_rejects_success_and_persists(store):
    def execute(*_):
        current=store.all()[0]
        assert _task_state(current)=='working'
        store.cancel(current['id'])
        return {'secret-result': 'provider-data'}
    worker, events=adapter(store, execute)
    task=worker.handle(request())['task']
    assert_rejected(task, 'canceled')
    assert task['metadata']['executionMayHaveOccurred'] is True
    assert store.get(task['id'])==task
    assert not any(event.event_type.value=='evaluation.completed' for event in events.events)


def test_cancel_submitted_before_dispatch(store):
    calls=[]; worker,_=adapter(store, lambda *_: calls.append(True))
    task=worker.handle(request(), _on_event=lambda event: store.cancel(event['task']['id']))['task']
    assert _task_state(task)=='canceled'
    assert task['metadata']['completionAuthoritative'] is False
    assert not calls


@pytest.mark.parametrize('failure', [ConnectionResetError('lost'), TimeoutError('timeout')])
def test_disconnect_outcome_is_unknown_never_success(store, failure):
    def execute(*_): raise failure
    worker,_=adapter(store, execute)
    task=worker.handle(request())['task']
    assert_rejected(task, 'failed')
    assert task['metadata']['executionMayHaveOccurred'] is True
    assert 'unknown' in str(task)


def test_client_disconnect_before_dispatch_does_not_execute(store):
    calls=[]; worker,_=adapter(store, lambda *_: calls.append(True))
    def disconnect(_): raise BrokenPipeError('client disconnected')
    task=worker.handle(request(), _on_event=disconnect)['task']
    assert _task_state(task)=='failed'
    assert task['metadata']['completionAuthoritative'] is False
    assert not calls


def test_approval_pause_is_nonterminal_and_cannot_auto_resume(store):
    calls=[]
    def execute(*_): calls.append(True); raise PermissionError('approval pending')
    worker,_=adapter(store, execute)
    events=worker.stream(request())
    assert_rejected(events[-1]['task'], 'auth-required')
    assert events[-1]['terminal'] is False
    task=worker.handle(request())['task']
    assert_rejected(task,'auth-required')
    assert len(calls)==1
    # Explicit new revision may execute only after current auth allows it.
    worker.executor=lambda *_: {'items': []}
    assert _task_state(worker.handle(request(2))['task'])=='completed'


def test_revocation_during_execution_and_verification_suppresses_completion(store):
    for during_assessment in [False, True]:
        active=[True]
        def execute(*_):
            if not during_assessment: active[0]=False
            return {'secret-result': 'provider-data'}
        worker,_=adapter(store, execute, lambda: active[0])
        if during_assessment:
            original=worker._assess_execution
            def assess(**kw):
                active[0]=False
                return original(**kw)
            worker._assess_execution=assess
        task=worker.handle(request(1 if not during_assessment else 2))['task']
        assert_rejected(task, 'auth-required')


def test_revision_scope_does_not_cancel_another_session(store):
    worker,_=adapter(store)
    assert _task_state(worker.handle(request(2, session='a'))['task'])=='completed'
    assert _task_state(worker.handle(request(1, session='b'))['task'])=='completed'


def test_replayed_revision_does_not_execute(store):
    calls=[]; worker,_=adapter(store, lambda *_: calls.append(True))
    worker.handle(request(2))
    task=worker.handle(request(1))['task']; assert_rejected(task,'failed')
    task=worker.handle(request(2,message_id='different'))['task']; assert_rejected(task,'failed')
    assert len(calls)==1
    with pytest.raises(ValueError,match='another intent revision'):
        worker.handle(request(3,message_id='message-2'))


@pytest.mark.parametrize('revision',[True,0,-1,'1',1.5,None])
def test_invalid_revision_fails_before_dispatch(revision):
    calls=[]; worker,_=adapter(A2ATaskStore(),lambda *_: calls.append(True))
    with pytest.raises(ValueError): worker.handle(request(revision))
    assert not calls


def test_postgres_revision_requests_fail_closed_without_calling_provider():
    calls=[]; store=PostgresA2ATaskStore('postgresql://fixture',lambda _: calls.append('connection'))
    worker,_=adapter(store,lambda *_: calls.append('provider'))
    body=request(); body['message'].pop('messageId')
    with pytest.raises(ValueError,match='local or SQLite'): worker.handle(body)
    assert not calls


def test_sqlite_revision_guard_survives_restart(tmp_path):
    path=str(tmp_path/'tasks.db'); first=SQLiteA2ATaskStore(path); worker,_=adapter(first)
    worker.handle(request(2)); first.close()
    reopened=SQLiteA2ATaskStore(path)
    try:
        worker,_=adapter(reopened)
        assert_rejected(worker.handle(request(1))['task'],'failed')
    finally: reopened.close()


@pytest.mark.parametrize('state',['TASK_STATE_AUTH_REQUIRED','TASK_STATE_INPUT_REQUIRED','auth-required','input-required'])
def test_pause_cannot_be_overwritten_but_can_be_canceled(store,state):
    task={'id':'paused','contextId':'context','status':{'state':state},'metadata':{'completionAuthoritative':False}}
    store.put(task)
    late=deepcopy(task); late['status']['state']='TASK_STATE_COMPLETED'; late['metadata']['completionAuthoritative']=True
    assert store.put(late)==task
    canceled=store.cancel('paused')
    assert _task_state(canceled)=='canceled'
    assert canceled['metadata']['completionAuthoritative'] is False


def test_context_identity_is_immutable(store):
    task={'id':'context-test','contextId':'original','status':{'state':'working'},'metadata':{'contextId':'original'}}
    store.put(task)
    changed=deepcopy(task); changed['contextId']='other'; changed['metadata']['contextId']='other'
    with pytest.raises(ValueError,match='context is immutable'): store.put(changed)


def test_rejected_duplicate_cannot_invalidate_running_revision(store):
    first={'id':'first','contextId':'c','status':{'state':'working'},'metadata':{'sessionId':'s','contextId':'c','intentId':'i','intentRevision':1,'revisionBound':True}}
    store.put(first)
    duplicate=deepcopy(first); duplicate['id']='duplicate'
    assert_rejected(store.put(duplicate),'failed')
    first['status']['state']='completed'; first['metadata']['completionAuthoritative']=True
    assert _task_state(store.put(first))=='completed'


def test_two_sqlite_instances_serialize_guard_and_write(tmp_path):
    path=str(tmp_path/'shared.db'); first=SQLiteA2ATaskStore(path); second=SQLiteA2ATaskStore(path)
    entered=Event(); release=Event(); second_done=Event(); results=[]
    original=first._guard_update
    def held_guard(task):
        result=original(task); entered.set(); assert release.wait(3); return result
    first._guard_update=held_guard
    task={'id':'one','contextId':'c','status':{'state':'working'},'metadata':{'sessionId':'s','contextId':'c','intentId':'i','intentRevision':1,'revisionBound':True}}
    other=deepcopy(task); other['id']='two'
    thread1=Thread(target=lambda: results.append(first.put(task)))
    def write_second():
        results.append(second.put(other)); second_done.set()
    thread2=Thread(target=write_second)
    thread1.start()
    try:
        assert entered.wait(3); thread2.start()
        assert not second_done.wait(.1)
    finally:
        release.set(); thread1.join(3); thread2.join(3)
        first.close(); second.close()
    assert not thread1.is_alive() and not thread2.is_alive()
    assert sum(bool(item['metadata'].get('revisionAccepted')) for item in results)==1
    assert_rejected(results[1],'failed')

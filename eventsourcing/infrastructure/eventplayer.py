from functools import reduce

from copy import deepcopy

from eventsourcing.domain.model.entity import TimestampedVersionedEntity
from eventsourcing.domain.model.snapshot import AbstractSnapshop
from eventsourcing.infrastructure.eventstore import AbstractEventStore
from eventsourcing.infrastructure.snapshotting import AbstractSnapshotStrategy, entity_from_snapshot


# def clone_object(initial_state):
#     initial_state_copy = object.__new__(type(initial_state))
#     initial_state_copy.__dict__.update(deepcopy(initial_state.__dict__))
#     return initial_state_copy


class EventPlayer(object):
    """
    Reconstitutes domain entities from domain events
    retrieved from the event store, optionally with snapshots.
    """

    def __init__(self, event_store, mutate_func, page_size=None, is_short=False, snapshot_strategy=None):
        assert isinstance(event_store, AbstractEventStore), event_store
        if snapshot_strategy is not None:
            assert isinstance(snapshot_strategy, AbstractSnapshotStrategy), snapshot_strategy
        self.event_store = event_store
        self.mutate_func = mutate_func
        self.page_size = page_size
        self.is_short = is_short
        self.snapshot_strategy = snapshot_strategy

    def replay_entity(self, entity_id, gt=None, gte=None, lt=None, lte=None, limit=None, initial_state=None,
                      query_descending=False):
        """
        Reconstitutes requested domain entity from domain events found in event store.
        """
        # Decide if query is in ascending order.
        #  - A "speed up" for when events are stored in descending order (e.g.
        #  in Cassandra) and it is faster to get them in that order.
        #  - This isn't useful when 'until' or 'after' or 'limit' are set,
        #    because the inclusiveness or exclusiveness of until and after
        #    and the end of the stream that is truncated by limit both depend on
        #    the direction of the query. Also paging backwards isn't useful, because
        #    all the events are needed eventually, so it would probably slow things
        #    down. Paging is intended to support replaying longer event streams, and
        #    only makes sense to work in ascending order.
        if self.is_short and gt is None and gte is None and lt is None and lte is None and self.page_size is None:
            is_ascending = False
        else:
            is_ascending = not query_descending

        # Get the domain events that are to be replayed.
        domain_events = self.get_domain_events(entity_id,
                                               gt=gt,
                                               gte=gte,
                                               lt=lt,
                                               lte=lte,
                                               limit=limit,
                                               is_ascending=is_ascending)

        # The events will be replayed in ascending order.
        if not is_ascending:
            domain_events = reversed(list(domain_events))

        # Replay the domain events, starting with the initial state.
        return self.replay_events(initial_state, domain_events)

    def replay_events(self, initial_state, domain_events):
        """
        Mutates initial state using the sequence of domain events.
        """
        return reduce(self.mutate_func, domain_events, initial_state)

    def get_domain_events(self, entity_id, gt=None, gte=None, lt=None, lte=None, limit=None, is_ascending=True):
        """
        Returns domain events for given entity ID.
        """
        # Get entity's domain events from the event store.
        domain_events = self.event_store.get_domain_events(
            entity_id=entity_id,
            gt=gt,
            gte=gte,
            lt=lt,
            lte=lte,
            limit=limit,
            page_size=self.page_size,
            is_ascending=is_ascending,
        )
        return domain_events

    def take_snapshot(self, entity_id, lt=None, lte=None):
        """
        Takes a snapshot of the entity as it existed after the most recent
        event, optionally less than or less than or equal to a particular position.
        """
        assert isinstance(self.snapshot_strategy, AbstractSnapshotStrategy)

        # Get the last event (optionally until a particular time).
        last_event = self.get_most_recent_event(entity_id, lt=lt, lte=lte)

        # If there aren't any events, there can't be a snapshot, so return None.
        if last_event is None:
            return None

        # If there is something to snapshot, then look for
        # the last snapshot before the last event.
        last_snapshot = self.get_snapshot(entity_id, lte=last_event.timestamp)

        if last_snapshot:
            assert isinstance(last_snapshot, AbstractSnapshop), type(last_snapshot)
            if last_snapshot.timestamp < last_event.timestamp:
                # There must be events after the snapshot, so get events after
                # the last event that was applied to the entity, and obtain the
                # initial entity state so those event can be applied to it.
                initial_state = entity_from_snapshot(last_snapshot)
                gte = initial_state._version
            else:
                # There's nothing to do.
                return last_snapshot
        else:
            # If there isn't a snapshot, start from scratch.
            initial_state = None
            gte = None

        # Get entity in the state after this event was applied.
        entity = self.replay_entity(entity_id, gte=gte, lt=lt, lte=lte, initial_state=initial_state)

        # Take a snapshot of the entity.
        return self.snapshot_strategy.take_snapshot(entity, timestamp=entity.last_modified_on)

    def get_snapshot(self, entity_id, lt=None, lte=None):
        """
        Returns a snapshot for given entity ID, according to the snapshot strategy.
        """
        if self.snapshot_strategy:
            return self.snapshot_strategy.get_snapshot(entity_id, lt=lt, lte=lte)

    def get_most_recent_event(self, entity_id, lt=None, lte=None):
        """
        Returns the most recent event for the given entity ID.
        """
        return self.event_store.get_most_recent_event(entity_id, lt=lt, lte=lte)

    # def fastforward(self, stale_entity, lt=None, lte=None):
    #     assert isinstance(stale_entity, TimestampedVersionedEntity)
    #
    #     # Replay the events since the entity version.
    #     fresh_entity = self.replay_entity(
    #         entity_id=stale_entity.id,
    #         gt=stale_entity.version,
    #         lt=lt,
    #         lte=lte,
    #         initial_state=stale_entity,
    #     )
    #
    #     # Return the fresh instance.
    #     return fresh_entity

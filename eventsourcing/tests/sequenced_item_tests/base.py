import json
import uuid
from time import time
from uuid import uuid4

import six

from eventsourcing.application.policies import CombinedPersistencePolicy
from eventsourcing.domain.model.events import TimestampedEntityEvent, VersionedEntityEvent, topic_from_domain_class
from eventsourcing.exceptions import SequencedItemError
from eventsourcing.infrastructure.activerecord import AbstractActiveRecordStrategy
from eventsourcing.infrastructure.eventstore import EventStore
from eventsourcing.infrastructure.iterators import SequencedItemIterator, ThreadedSequencedItemIterator
from eventsourcing.infrastructure.transcoding import SequencedItem, SequencedItemMapper, StoredEvent
from eventsourcing.tests.datastore_tests.base import AbstractDatastoreTestCase


class ActiveRecordStrategyTestCase(AbstractDatastoreTestCase):
    def __init__(self, *args, **kwargs):
        super(ActiveRecordStrategyTestCase, self).__init__(*args, **kwargs)
        self._active_record_strategy = None

    def setUp(self):
        super(ActiveRecordStrategyTestCase, self).setUp()
        if self.datastore is not None:
            self.datastore.setup_connection()
            self.datastore.setup_tables()

    def tearDown(self):
        self._active_record_strategy = None
        if self.datastore is not None:
            self.datastore.drop_tables()
            self.datastore.drop_connection()
        super(ActiveRecordStrategyTestCase, self).tearDown()

    @property
    def active_record_strategy(self):
        """
        :rtype: AbstractActiveRecordStrategy
        """
        if self._active_record_strategy is None:
            self._active_record_strategy = self.construct_active_record_strategy()
        return self._active_record_strategy

    def construct_active_record_strategy(self):
        raise NotImplementedError()

    def construct_positions(self):
        raise NotImplementedError()

    def EXAMPLE_EVENT_TOPIC1(self):
        raise NotImplementedError()

    def EXAMPLE_EVENT_TOPIC2(self):
        raise NotImplementedError()

    def test(self):
        sequence_id1 = uuid.uuid1()
        sequence_id2 = uuid.uuid1()

        # Check repo returns None when there aren't any items.
        self.assertEqual(self.active_record_strategy.get_items(sequence_id1), [])

        position1, position2, position3 = self.construct_positions()

        self.assertLess(position1, position2)
        self.assertLess(position2, position3)

        # Append an item.
        data1 = json.dumps({'name': 'value1'})
        item1 = SequencedItem(
            sequence_id=sequence_id1,
            position=position1,
            topic=self.EXAMPLE_EVENT_TOPIC1,
            data=data1,
        )
        self.active_record_strategy.append_item(item1)

        # Append an item to a different sequence.
        data2 = json.dumps({'name': 'value2'})
        item2 = SequencedItem(
            sequence_id=sequence_id2,
            position=position1,
            topic=self.EXAMPLE_EVENT_TOPIC1,
            data=data2,
        )
        self.active_record_strategy.append_item(item2)

        # Check the get_item() method returns item at position.
        retrieved_item = self.active_record_strategy.get_item(sequence_id1, position1)
        self.assertEqual(retrieved_item.sequence_id, sequence_id1)
        self.assertEqual(retrieved_item.position, position1)

        # Check index error is raised when item does not exist at position.
        with self.assertRaises(IndexError):
            self.active_record_strategy.get_item(sequence_id1, position2)

        # Check repo returns the item.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1)
        self.assertEqual(len(retrieved_items), 1)
        self.assertIsInstance(retrieved_items[0], SequencedItem)
        self.assertEqual(retrieved_items[0].sequence_id, item1.sequence_id)
        self.assertEqual(retrieved_items[0].position, position1)
        self.assertEqual(retrieved_items[0].data, item1.data)
        self.assertEqual(retrieved_items[0].topic, item1.topic)

        # Check raises SequencedItemError when appending an item at same position in same sequence.
        data3 = json.dumps({'name': 'value3'})
        item3 = SequencedItem(
            sequence_id=item1.sequence_id,
            position=position1,
            topic=self.EXAMPLE_EVENT_TOPIC2,
            data=data3,
        )
        self.assertEqual(item1.sequence_id, item3.sequence_id)
        self.assertEqual(position1, item3.position)
        self.assertNotEqual(item1.topic, item3.topic)
        self.assertNotEqual(item1.data, item3.data)
        with self.assertRaises(SequencedItemError):
            self.active_record_strategy.append_item(item3)

        # Append a second item at the next position.
        item4 = SequencedItem(
            sequence_id=item1.sequence_id,
            position=position2,
            topic=self.EXAMPLE_EVENT_TOPIC2,
            data=data3,
        )
        self.active_record_strategy.append_item(item4)

        # Check there are two items in the sequence.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1)
        self.assertEqual(len(retrieved_items), 2)

        # Append a third item to the sequence at the next position.
        item5 = SequencedItem(
            sequence_id=item1.sequence_id,
            position=position3,
            topic=self.EXAMPLE_EVENT_TOPIC2,
            data=data3,
        )
        self.active_record_strategy.append_item(item5)

        # Check there are three items.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1)
        self.assertEqual(len(retrieved_items), 3)

        # Check the items are in sequential order.
        self.assertIsInstance(retrieved_items[0], SequencedItem)
        self.assertEqual(retrieved_items[0].sequence_id, item1.sequence_id)
        self.assertEqual(retrieved_items[0].position, position1)
        self.assertEqual(retrieved_items[0].topic, item1.topic)
        self.assertEqual(retrieved_items[0].data, item1.data)

        self.assertIsInstance(retrieved_items[1], SequencedItem)
        self.assertEqual(retrieved_items[1].sequence_id, item3.sequence_id)
        self.assertEqual(retrieved_items[1].position, position2)
        self.assertEqual(retrieved_items[1].topic, item3.topic)
        self.assertEqual(retrieved_items[1].data, item3.data)

        self.assertIsInstance(retrieved_items[2], SequencedItem)
        self.assertEqual(retrieved_items[2].sequence_id, item5.sequence_id)
        self.assertEqual(retrieved_items[2].position, position3)
        self.assertEqual(retrieved_items[2].topic, item5.topic)
        self.assertEqual(retrieved_items[2].data, item5.data)

        # Get items greater than a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, gt=position1)
        self.assertEqual(len(retrieved_items), 2)
        self.assertEqual(retrieved_items[0].position, position2)
        self.assertEqual(retrieved_items[1].position, position3)

        # Get items greater then or equal to a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, gte=position2)
        self.assertEqual(len(retrieved_items), 2)
        self.assertEqual(retrieved_items[0].position, position2)
        self.assertEqual(retrieved_items[1].position, position3)

        # Get items less than a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, lt=position3)
        self.assertEqual(len(retrieved_items), 2)
        self.assertEqual(retrieved_items[0].position, position1)
        self.assertEqual(retrieved_items[1].position, position2)

        # Get items less then or equal to a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, lte=position2)
        self.assertEqual(len(retrieved_items), 2)
        self.assertEqual(retrieved_items[0].position, position1)
        self.assertEqual(retrieved_items[1].position, position2)

        # Get items greater then or equal to a position and less then or equal to a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, gte=position2, lte=position2)
        self.assertEqual(len(retrieved_items), 1)
        self.assertEqual(retrieved_items[0].position, position2)

        # Get items greater then or equal to a position and less then a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, gte=position2, lt=position3)
        self.assertEqual(len(retrieved_items), 1)
        self.assertEqual(retrieved_items[0].position, position2)

        # Get items greater then a position and less then or equal to a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, gt=position1, lte=position2)
        self.assertEqual(len(retrieved_items), 1)
        self.assertEqual(retrieved_items[0].position, position2)

        # Get items greater a position and less a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, gt=position1, lt=position3)
        self.assertEqual(len(retrieved_items), 1)
        self.assertEqual(retrieved_items[0].position, position2)

        # Get items with a limit.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, limit=1)
        self.assertEqual(len(retrieved_items), 1)
        self.assertEqual(retrieved_items[0].position, position1)

        # Get items with a limit, and with descending query (so that we get the last ones).
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, limit=2,
                                                                query_ascending=False)
        self.assertEqual(len(retrieved_items), 2)
        self.assertEqual(retrieved_items[0].position, position2)
        self.assertEqual(retrieved_items[1].position, position3)

        # Get items with a limit and descending query, greater than a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, limit=2, gt=position2,
                                                                query_ascending=False)
        self.assertEqual(len(retrieved_items), 1)
        self.assertEqual(retrieved_items[0].position, position3)

        # Get items with a limit and descending query, less than a position.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1, limit=2, lt=position3,
                                                                query_ascending=False)
        self.assertEqual(len(retrieved_items), 2)
        self.assertEqual(retrieved_items[0].position, position1)
        self.assertEqual(retrieved_items[1].position, position2)

        # Get items in descending order, queried in ascending order.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1,
                                                                results_ascending=False)
        self.assertEqual(len(retrieved_items), 3)
        self.assertEqual(retrieved_items[0].position, position3)
        self.assertEqual(retrieved_items[2].position, position1)

        # Get items in descending order, queried in descending order.
        retrieved_items = self.active_record_strategy.get_items(sequence_id1,
                                                                query_ascending=False,
                                                                results_ascending=False)
        self.assertEqual(len(retrieved_items), 3)
        self.assertEqual(retrieved_items[0].position, position3)
        self.assertEqual(retrieved_items[2].position, position1)

        # Iterate over all items in all sequences.
        retrieved_items = self.active_record_strategy.all_items()
        retrieved_items = list(retrieved_items)

        # Not always in order, but check the number of events.
        self.assertEqual(len(retrieved_items), 4)

        # Check we can get all the sequence IDs.
        entity_ids = set([i.sequence_id for i in retrieved_items])
        self.assertEqual(entity_ids, {sequence_id1, sequence_id2})


class WithActiveRecordStrategies(AbstractDatastoreTestCase):
    def __init__(self, *args, **kwargs):
        super(WithActiveRecordStrategies, self).__init__(*args, **kwargs)
        self._integer_sequence_strategy = None
        self._timestamp_sequence_strategy = None

    def setUp(self):
        super(WithActiveRecordStrategies, self).setUp()
        if self.datastore is not None:
            self.datastore.setup_connection()
            self.datastore.setup_tables()

    def tearDown(self):
        self._timestamp_sequence_strategy = None
        self._integer_sequence_strategy = None
        if self.datastore is not None:
            self.datastore.drop_tables()
            self.datastore.drop_connection()
        super(WithActiveRecordStrategies, self).tearDown()

    @property
    def integer_sequence_active_record_strategy(self):
        if self._integer_sequence_strategy is None:
            self._integer_sequence_strategy = self.construct_integer_sequence_active_record_strategy()
        return self._integer_sequence_strategy

    @property
    def timestamp_sequence_active_record_strategy(self):
        if self._timestamp_sequence_strategy is None:
            self._timestamp_sequence_strategy = self.construct_timestamp_sequence_active_record_strategy()
        return self._timestamp_sequence_strategy

    def construct_integer_sequence_active_record_strategy(self):
        """
        :rtype: eventsourcing.infrastructure.storedevents.activerecord.AbstractActiveRecordStrategy
        """
        raise NotImplementedError

    def construct_timestamp_sequence_active_record_strategy(self):
        """
        :rtype: eventsourcing.infrastructure.storedevents.activerecord.AbstractActiveRecordStrategy
        """
        raise NotImplementedError


class ExampleVersionEntityEvent1(VersionedEntityEvent):
    pass


class ExampleVersionEntityEvent2(VersionedEntityEvent):
    pass


class ExampleTimestampEntityEvent1(TimestampedEntityEvent):
    pass


class ExampleTimestampEntityEvent2(TimestampedEntityEvent):
    pass


class IntegerSequencedItemTestCase(ActiveRecordStrategyTestCase):
    EXAMPLE_EVENT_TOPIC1 = topic_from_domain_class(ExampleVersionEntityEvent1)
    EXAMPLE_EVENT_TOPIC2 = topic_from_domain_class(ExampleVersionEntityEvent2)

    def construct_positions(self):
        return 0, 1, 2


class TimestampSequencedItemTestCase(ActiveRecordStrategyTestCase):
    EXAMPLE_EVENT_TOPIC1 = topic_from_domain_class(ExampleTimestampEntityEvent1)
    EXAMPLE_EVENT_TOPIC2 = topic_from_domain_class(ExampleTimestampEntityEvent2)

    def construct_positions(self):
        t1 = time()
        return t1, t1 + 0.00001, t1 + 0.00002


class SequencedItemIteratorTestCase(WithActiveRecordStrategies):

    ENTITY_ID1 = uuid4()

    @property
    def entity_id(self):
        return self.ENTITY_ID1

    @property
    def num_events(self):
        return 12

    @property
    def iterator_cls(self):
        """
        Returns iterator class.
        """
        raise NotImplementedError()

    def construct_iterator(self, is_ascending, page_size, gt=None, lte=None, limit=None):
        return self.iterator_cls(
            active_record_strategy=self.integer_sequence_active_record_strategy,
            sequence_id=self.entity_id,
            page_size=page_size,
            gt=gt,
            lte=lte,
            limit=limit,
            is_ascending=is_ascending,
        )

    def setup_sequenced_items(self):
        self.sequenced_items = []
        self.number_of_sequenced_items = 12
        for i in six.moves.range(self.number_of_sequenced_items):
            sequenced_item = SequencedItem(
                sequence_id=self.entity_id,
                position=i,
                topic='eventsourcing.example.domain_model#Example.Created',
                data='{"i":%s,"entity_id":"%s","timestamp":%s}' % (
                    i, self.entity_id, time()
                )
            )
            self.sequenced_items.append(sequenced_item)
            self.integer_sequence_active_record_strategy.append_item(sequenced_item)

    def test(self):
        self.setup_sequenced_items()

        assert isinstance(self.integer_sequence_active_record_strategy, AbstractActiveRecordStrategy)
        stored_events = self.integer_sequence_active_record_strategy.get_items(
            sequence_id=self.entity_id
        )
        stored_events = list(stored_events)
        self.assertEqual(len(stored_events), self.num_events)

        # # Check can get all events in ascending order.
        self.assert_iterator_yields_events(
            is_ascending=True,
            expect_at_start=self.sequenced_items[0].data,
            expect_at_end=self.sequenced_items[-1].data,
            expect_item_count=12,
            expect_page_count=3,
            expect_query_count=3,
            page_size=5,
        )

        # In descending order.
        self.assert_iterator_yields_events(
            is_ascending=False,
            expect_at_start=self.sequenced_items[-1].data,
            expect_at_end=self.sequenced_items[0].data,
            expect_item_count=12,
            expect_page_count=3,
            expect_query_count=3,
            page_size=5,
        )

        # Limit number of items.
        self.assert_iterator_yields_events(
            is_ascending=False,
            expect_at_start=self.sequenced_items[-1].data,
            expect_at_end=self.sequenced_items[-2].data,
            expect_item_count=2,
            expect_page_count=1,
            expect_query_count=1,
            page_size=5,
            limit=2,
        )

        # Match the page size to the number of events.
        self.assert_iterator_yields_events(
            is_ascending=True,
            expect_at_start=self.sequenced_items[0].data,
            expect_at_end=self.sequenced_items[-1].data,
            expect_item_count=12,
            expect_page_count=1,
            expect_query_count=2,
            page_size=self.num_events,
        )

        # Queries are minimised if we set a limit.
        self.assert_iterator_yields_events(
            is_ascending=True,
            expect_at_start=self.sequenced_items[0].data,
            expect_at_end=self.sequenced_items[-1].data,
            expect_item_count=12,
            expect_page_count=1,
            expect_query_count=1,
            page_size=self.num_events,
            limit=12,
        )

    def assert_iterator_yields_events(self, is_ascending, expect_at_start, expect_at_end, expect_item_count=1,
                                      expect_page_count=0, expect_query_count=0, page_size=1, limit=None):
        iterator = self.construct_iterator(is_ascending, page_size, limit=limit)
        retrieved_events = list(iterator)
        self.assertEqual(len(retrieved_events), expect_item_count, retrieved_events)
        self.assertEqual(iterator.page_counter, expect_page_count)
        self.assertEqual(iterator.query_counter, expect_query_count)
        self.assertEqual(iterator.all_item_counter, expect_item_count)
        self.assertEqual(expect_at_start, retrieved_events[0].data)
        self.assertEqual(expect_at_end, retrieved_events[-1].data)


class SimpleSequencedItemteratorTestCase(SequencedItemIteratorTestCase):
    @property
    def iterator_cls(self):
        return SequencedItemIterator


class ThreadedSequencedItemIteratorTestCase(SequencedItemIteratorTestCase):
    @property
    def iterator_cls(self):
        return ThreadedSequencedItemIterator


class WithPersistencePolicy(WithActiveRecordStrategies):
    """
    Base class for test cases that required a persistence subscriber.
    """

    def setUp(self):
        super(WithPersistencePolicy, self).setUp()
        # Setup the persistence subscriber.
        self.versioned_entity_event_store = EventStore(
            active_record_strategy=self.integer_sequence_active_record_strategy,
            sequenced_item_mapper=SequencedItemMapper(
                position_attr_name='entity_version'
            )
        )
        self.timestamped_entity_event_store = EventStore(
            active_record_strategy=self.timestamp_sequence_active_record_strategy,
            sequenced_item_mapper=SequencedItemMapper(
                position_attr_name='timestamp'
            )
        )
        self.persistence_policy = CombinedPersistencePolicy(
            versioned_entity_event_store=self.versioned_entity_event_store,
            timestamped_entity_event_store=self.timestamped_entity_event_store,
        )

    def tearDown(self):
        # Close the persistence subscriber.
        self.persistence_policy.close()
        super(WithPersistencePolicy, self).tearDown()

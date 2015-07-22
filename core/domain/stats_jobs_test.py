# coding: utf-8
#
# Copyright 2014 The Oppia Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

__author__ = 'Stephanie Federwisch'

"""Tests for statistics continuous computations."""

from core import jobs_registry
from core.domain import event_services
from core.domain import exp_domain
from core.domain import exp_services
from core.domain import stats_jobs
from core.domain import stats_services
from core.platform import models
(stats_models,) = models.Registry.import_models([models.NAMES.statistics])
from core.tests import test_utils
import feconf


class ModifiedStatisticsAggregator(stats_jobs.StatisticsAggregator):
    """A modified StatisticsAggregator that does not start a new batch
    job when the previous one has finished.
    """
    @classmethod
    def _get_batch_job_manager_class(cls):
        return ModifiedStatisticsMRJobManager

    @classmethod
    def _kickoff_batch_job_after_previous_one_ends(cls):
        pass


class ModifiedStatisticsMRJobManager(stats_jobs.StatisticsMRJobManager):

    @classmethod
    def _get_continuous_computation_class(cls):
        return ModifiedStatisticsAggregator


class StatsAggregatorUnitTests(test_utils.GenericTestBase):
    """Tests for statistics aggregations."""

    ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS = [
        ModifiedStatisticsAggregator]

    def _record_start(self, exp_id, exp_version, state, session_id):
        event_services.StartExplorationEventHandler.record(
            exp_id, exp_version, state, session_id, {},
            feconf.PLAY_TYPE_NORMAL)

    def _record_leave(self, exp_id, exp_version, state, session_id):
        event_services.MaybeLeaveExplorationEventHandler.record(
            exp_id, exp_version, state, session_id, 27, {},
            feconf.PLAY_TYPE_NORMAL)

    def _record_complete(self, exp_id, exp_version, state, session_id):
        event_services.CompleteExplorationEventHandler.record(
            exp_id, exp_version, state, session_id, 27, {},
            feconf.PLAY_TYPE_NORMAL)

    def _record_state_hit(self, exp_id, exp_version, state, session_id):
        event_services.StateHitEventHandler.record(
            exp_id, exp_version, state, session_id, {},
            feconf.PLAY_TYPE_NORMAL)

    def _create_state_counter(self, exp_id, state, first_entry_count):
        counter = stats_models.StateCounterModel.get_or_create(exp_id, state)
        counter.first_entry_count = first_entry_count
        counter.put()

    def test_state_hit(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):
            exp_id = 'eid'
            exp_version = 1
            exploration = self.save_new_valid_exploration(exp_id, 'owner')
            state = exploration.init_state_name
            state2 = 'sid2'

            self._record_state_hit(exp_id, exp_version, state, 'session1')
            self._record_state_hit(exp_id, exp_version, state, 'session2')
            self._create_state_counter(exp_id, state, 18)
            self._record_state_hit(exp_id, exp_version, state2, 'session1')
            self._create_state_counter(exp_id, state2, 9)
            self.process_and_flush_pending_tasks()

            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()

            output_model = stats_jobs.StatisticsAggregator.get_statistics(
                exp_id, exp_version)
            self.assertEqual(
                output_model['state_hit_counts'][state]['first_entry_count'],
                2)
            self.assertEqual(
                output_model['state_hit_counts'][state2]['first_entry_count'],
                1)

            output_model = stats_jobs.StatisticsAggregator.get_statistics(
                exp_id, stats_jobs._NO_SPECIFIED_VERSION_STRING)
            self.assertEqual(
                output_model['state_hit_counts'][state]['first_entry_count'],
                18)
            self.assertEqual(
                output_model['state_hit_counts'][state2]['first_entry_count'],
                9)

            output_model = stats_jobs.StatisticsAggregator.get_statistics(
                exp_id, stats_jobs._ALL_VERSIONS_STRING)
            self.assertEqual(
                output_model['state_hit_counts'][state]['first_entry_count'],
                20)
            self.assertEqual(
                output_model['state_hit_counts'][state2]['first_entry_count'],
                10)

    def test_no_completion(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):
            exp_id = 'eid'
            exp_version = 1
            exploration = self.save_new_valid_exploration(exp_id, 'owner')
            state = exploration.init_state_name

            self._record_start(exp_id, exp_version, state, 'session1')
            self._record_start(exp_id, exp_version, state, 'session2')
            self.process_and_flush_pending_tasks()

            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()

            model_id = '%s:%s' % (exp_id, exp_version)
            output_model = stats_models.ExplorationAnnotationsModel.get(
                model_id)
            self.assertEqual(output_model.num_starts, 2)
            self.assertEqual(output_model.num_completions, 0)

    def test_all_complete(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):
            exp_id = 'eid'
            exp_version = 1
            exploration = self.save_new_valid_exploration(exp_id, 'owner')
            state = exploration.init_state_name

            self._record_start(exp_id, exp_version, state, 'session1')
            self._record_complete(
                exp_id, exp_version, stats_jobs.OLD_END_DEST, 'session1')

            self._record_start(exp_id, exp_version, state, 'session2')
            self._record_complete(
                exp_id, exp_version, stats_jobs.OLD_END_DEST, 'session2')
            self.process_and_flush_pending_tasks()

            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()

            model_id = '%s:%s' % (exp_id, exp_version)
            output_model = stats_models.ExplorationAnnotationsModel.get(
                model_id)
            self.assertEqual(output_model.num_starts, 2)
            self.assertEqual(output_model.num_completions, 2)

    def test_one_leave_and_one_complete(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):
            exp_id = 'eid'
            exp_version = 1
            exploration = self.save_new_valid_exploration(exp_id, 'owner')
            state = exploration.init_state_name

            self._record_start(exp_id, exp_version, state, 'session1')
            self._record_leave(exp_id, exp_version, state, 'session1')

            self._record_start(exp_id, exp_version, state, 'session2')
            self._record_complete(
                exp_id, exp_version, 'END', 'session2')
            self.process_and_flush_pending_tasks()

            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()

            model_id = '%s:%s' % (exp_id, exp_version)
            output_model = stats_models.ExplorationAnnotationsModel.get(
                model_id)
            self.assertEqual(output_model.num_starts, 2)
            self.assertEqual(output_model.num_completions, 1)

    def test_one_leave_and_one_complete_same_session(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):
            exp_id = 'eid'
            exp_version = 1
            exploration = self.save_new_valid_exploration(exp_id, 'owner')
            init_state = exploration.init_state_name

            self._record_start(exp_id, exp_version, init_state, 'session1')
            self._record_state_hit(exp_id, exp_version, init_state, 'session1')
            self._record_leave(exp_id, exp_version, init_state, 'session1')
            self._record_state_hit(exp_id, exp_version, 'END', 'session1')
            self._record_complete(exp_id, exp_version, 'END', 'session1')
            self.process_and_flush_pending_tasks()

            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()

            model_id = '%s:%s' % (exp_id, exp_version)
            output_model = stats_models.ExplorationAnnotationsModel.get(
                model_id)
            self.assertEqual(output_model.num_starts, 1)
            self.assertEqual(output_model.num_completions, 1)

            stats_dict = ModifiedStatisticsAggregator.get_statistics(exp_id, 1)
            self.assertEqual(stats_dict['start_exploration_count'], 1)
            self.assertEqual(stats_dict['complete_exploration_count'], 1)
            self.assertEqual(stats_dict['state_hit_counts'], {
                exploration.init_state_name: {
                    'first_entry_count': 1,
                    'no_answer_count': 0,
                    'total_entry_count': 1,
                },
                'END': {
                    'first_entry_count': 1,
                    'total_entry_count': 1,
                }
            })

    def test_multiple_maybe_leaves_same_session(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):
            exp_id = 'eid'
            exp_version = 1
            exploration = self.save_new_valid_exploration(exp_id, 'owner')
            state = exploration.init_state_name

            self._record_start(exp_id, exp_version, state, 'session1')
            self._record_leave(exp_id, exp_version, state, 'session1')
            self._record_leave(exp_id, exp_version, state, 'session1')
            self._record_complete(
                exp_id, exp_version, stats_jobs.OLD_END_DEST, 'session1')

            self._record_start(exp_id, exp_version, state, 'session2')
            self._record_leave(exp_id, exp_version, state, 'session2')
            self._record_leave(exp_id, exp_version, state, 'session2')
            self.process_and_flush_pending_tasks()

            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()

            model_id = '%s:%s' % (exp_id, exp_version)
            output_model = stats_models.ExplorationAnnotationsModel.get(
                model_id)
            self.assertEqual(output_model.num_starts, 2)
            self.assertEqual(output_model.num_completions, 1)

    def test_multiple_explorations(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):

            exp_version = 1
            exp_id_1 = 'eid1'
            exploration = self.save_new_valid_exploration(exp_id_1, 'owner')
            state_1_1 = exploration.init_state_name
            exp_id_2 = 'eid2'
            exploration = self.save_new_valid_exploration(exp_id_2, 'owner')
            state_2_1 = exploration.init_state_name

            EMPTY_STATE_HIT_COUNTS_DICT = {
                feconf.DEFAULT_INIT_STATE_NAME: {
                    'total_entry_count': 0,
                    'no_answer_count': 0,
                    'first_entry_count': 0,
                }
            }

            # Record 2 start events for exp_id_1 and 1 start event for
            # exp_id_2.
            self._record_start(exp_id_1, exp_version, state_1_1, 'session1')
            self._record_start(exp_id_1, exp_version, state_1_1, 'session2')
            self._record_start(exp_id_2, exp_version, state_2_1, 'session3')
            self.process_and_flush_pending_tasks()
            ModifiedStatisticsAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()
            results = ModifiedStatisticsAggregator.get_statistics(
                exp_id_1, 'all')
            self.assertDictContainsSubset({
                'start_exploration_count': 2,
                'complete_exploration_count': 0,
                'state_hit_counts': EMPTY_STATE_HIT_COUNTS_DICT,
            }, results)
            results = ModifiedStatisticsAggregator.get_statistics(
                exp_id_2, 'all')
            self.assertDictContainsSubset({
                'start_exploration_count': 1,
                'complete_exploration_count': 0,
                'state_hit_counts': EMPTY_STATE_HIT_COUNTS_DICT,
            }, results)

            # Record 1 more start event for exp_id_1 and 1 more start event
            # for exp_id_2.
            self._record_start(exp_id_1, exp_version, state_1_1, 'session2')
            self._record_start(exp_id_2, exp_version, state_2_1, 'session3')
            self.process_and_flush_pending_tasks()
            results = ModifiedStatisticsAggregator.get_statistics(
                exp_id_1, 'all')
            self.assertDictContainsSubset({
                'start_exploration_count': 3,
                'complete_exploration_count': 0,
                'state_hit_counts': EMPTY_STATE_HIT_COUNTS_DICT,
            }, results)
            results = ModifiedStatisticsAggregator.get_statistics(
                exp_id_2, 'all')
            self.assertDictContainsSubset({
                'start_exploration_count': 2,
                'complete_exploration_count': 0,
                'state_hit_counts': EMPTY_STATE_HIT_COUNTS_DICT,
            }, results)


class ModifiedInteractionAnswerSummariesAggregator(
        stats_jobs.StatisticsAggregator):
    """A modified InteractionAnswerSummariesAggregator that does not start
    a new batch job when the previous one has finished.
    """
    @classmethod
    def _get_batch_job_manager_class(cls):
        return ModifiedInteractionAnswerSummariesMRJobManager

    @classmethod
    def _kickoff_batch_job_after_previous_one_ends(cls):
        pass


class ModifiedInteractionAnswerSummariesMRJobManager(
        stats_jobs.InteractionAnswerSummariesMRJobManager):

    @classmethod
    def _get_continuous_computation_class(cls):
        return ModifiedInteractionAnswerSummariesAggregator


class InteractionAnswerSummariesAggregatorTests(test_utils.GenericTestBase):
    """Tests for interaction answer view aggregations."""

    ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS = [
        ModifiedInteractionAnswerSummariesAggregator]
    DEFAULT_RULESPEC_STR = exp_domain.DEFAULT_RULESPEC_STR

    def _record_start(self, exp_id, exp_version, state_name, session_id):
        event_services.StartExplorationEventHandler.record(
            exp_id, exp_version, state_name, session_id, {},
            feconf.PLAY_TYPE_NORMAL)

    def test_one_answer(self):
        with self.swap(
                jobs_registry, 'ALL_CONTINUOUS_COMPUTATION_MANAGERS',
                self.ALL_CONTINUOUS_COMPUTATION_MANAGERS_FOR_TESTS):

            # setup example exploration
            exp_id = 'eid'
            exp = self.save_new_valid_exploration(exp_id, 'fake@user.com')
            FIRST_STATE_NAME = exp.init_state_name
            SECOND_STATE_NAME = 'State 2'
            exp_services.update_exploration('fake@user.com', exp_id, [{
                'cmd': 'edit_state_property',
                'state_name': FIRST_STATE_NAME,
                'property_name': 'widget_id',
                'new_value': 'MultipleChoiceInput',
            }, {
                'cmd': 'add_state',
                'state_name': SECOND_STATE_NAME,
            }, {
                'cmd': 'edit_state_property',
                'state_name': SECOND_STATE_NAME,
                'property_name': 'widget_id',
                'new_value': 'MultipleChoiceInput',
            }], 'Add new state')
            exp = exp_services.get_exploration_by_id(exp_id)
            exp_version = exp.version

            time_spent = 5.0
            params = {}

            self._record_start(exp_id, exp_version, FIRST_STATE_NAME,
                               'session1')
            self._record_start(exp_id, exp_version, FIRST_STATE_NAME,
                               'session2')
            self.process_and_flush_pending_tasks()

            # add some answers
            event_services.AnswerSubmissionEventHandler.record(
                exp_id, exp_version, FIRST_STATE_NAME, 'submit',
                self.DEFAULT_RULESPEC_STR, 'session1', time_spent, params,
                'answer1')
            event_services.AnswerSubmissionEventHandler.record(
                exp_id, exp_version, FIRST_STATE_NAME, 'submit',
                self.DEFAULT_RULESPEC_STR, 'session2', time_spent, params,
                'answer1')
            event_services.AnswerSubmissionEventHandler.record(
                exp_id, exp_version, FIRST_STATE_NAME, 'submit',
                self.DEFAULT_RULESPEC_STR, 'session1', time_spent, params,
                'answer2')
            event_services.AnswerSubmissionEventHandler.record(
                exp_id, exp_version, SECOND_STATE_NAME, 'submit',
                self.DEFAULT_RULESPEC_STR, 'session2', time_spent, params,
                'answer3')

            # Run job on exploration with answers
            ModifiedInteractionAnswerSummariesAggregator.start_computation()
            self.assertEqual(self.count_jobs_in_taskqueue(), 1)
            self.process_and_flush_pending_tasks()
            self.assertEqual(self.count_jobs_in_taskqueue(), 0)

            calc_id = 'AnswerCounts'
            
            # get job output of first state and check it
            calc_output_domain_object = (
                stats_jobs.InteractionAnswerSummariesAggregator.get_calc_output(
                    exp_id, exp_version, FIRST_STATE_NAME, calc_id))
            self.assertEqual('AnswerCounts',
                             calc_output_domain_object.calculation_id)

            calculation_output = calc_output_domain_object.calculation_output

            expected_calculation_output = [{
                'answer': 'answer1',
                'frequency': 2
            }, {
                'answer': 'answer2',
                'frequency': 1
            }]

            self.assertEqual(calculation_output,
                             expected_calculation_output)

            # get job output of second state and check it
            calc_output_domain_object = (
                stats_jobs.InteractionAnswerSummariesAggregator.get_calc_output(
                    exp_id, exp_version, SECOND_STATE_NAME, calc_id))

            self.assertEqual('AnswerCounts',
                             calc_output_domain_object.calculation_id)
            
            calculation_output = calc_output_domain_object.calculation_output

            expected_calculation_output = [{
                'answer': 'answer3',
                'frequency': 1
            }]

            self.assertEqual(calculation_output, expected_calculation_output)


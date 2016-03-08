"""
Tests for the reference loader for EarningsCalendar.
"""
from functools import partial
from unittest import TestCase

import blaze as bz
from blaze.compute.core import swap_resources_into_scope
from contextlib2 import ExitStack
import pandas as pd
from six import iteritems

from zipline.pipeline.common import (
    ANNOUNCEMENT_FIELD_NAME,
    DAYS_SINCE_PREV_DIVIDEND_ANNOUNCEMENT,
    DAYS_SINCE_PREV_EX_DATE,
    DAYS_TO_NEXT_EX_DATE,
    NEXT_AMOUNT,
    NEXT_EX_DATE,
    NEXT_PAY_DATE,
    PREVIOUS_ANNOUNCEMENT,
    PREVIOUS_EX_DATE,
    PREVIOUS_PAY_DATE,
    PREVIOUS_AMOUNT,
    SID_FIELD_NAME,
    TS_FIELD_NAME,
    AD_FIELD_NAME,
    CASH_AMOUNT_FIELD_NAME,
    EX_DATE_FIELD_NAME,
    PAY_DATE_FIELD_NAME
)
from zipline.pipeline.data.dividends import CashDividends
from zipline.pipeline.factors.events import (
    BusinessDaysSinceDividendAnnouncement,
    BusinessDaysSincePreviousExDate,
    BusinessDaysUntilNextExDate
)
from zipline.pipeline.loaders.earnings import EarningsCalendarLoader
from zipline.pipeline.loaders.blaze import (
    BlazeEarningsCalendarLoader,
)
from zipline.utils.test_utils import (
    make_simple_equity_info,
    tmp_asset_finder,
)
from .base import EventLoaderCommonMixin, DATE_FIELD_NAME


dividends = [
    # K1--K2--A1--A2.
    pd.DataFrame({
        CASH_AMOUNT_FIELD_NAME: [1, 15],
        EX_DATE_FIELD_NAME: [],
        PAY_DATE_FIELD_NAME: []
    }),
    # K1--K2--A2--A1.
    pd.DataFrame({
        CASH_AMOUNT_FIELD_NAME: [7, 13],
        EX_DATE_FIELD_NAME: [],
        PAY_DATE_FIELD_NAME: []
    }),
    # K1--A1--K2--A2.
    pd.DataFrame({
        CASH_AMOUNT_FIELD_NAME: [3, 1],
        EX_DATE_FIELD_NAME: [],
        PAY_DATE_FIELD_NAME: []
    }),
    # K1 == K2.
    pd.DataFrame({
        CASH_AMOUNT_FIELD_NAME: [6, 23],
        EX_DATE_FIELD_NAME: [],
        PAY_DATE_FIELD_NAME: []
    }),
    pd.DataFrame(
        columns=[CASH_AMOUNT_FIELD_NAME,
                 EX_DATE_FIELD_NAME,
                 PAY_DATE_FIELD_NAME],
        dtype='datetime64[ns]'
    ),
]


def create_dividends_tst_frame(cases, field_to_drop):
    cash_dividends = {
        sid:
            pd.concat([df, dividends[sid]], axis=1).drop(
                field_to_drop, 1)
            for sid, df
            in enumerate(case.rename(columns={DATE_FIELD_NAME:
                                              AD_FIELD_NAME}
                                     )
                         for case in cases
                         )
            }
    return cash_dividends


class CashDividendsLoaderTestCase(TestCase, EventLoaderCommonMixin):
    """
    Tests for loading the earnings announcement data.
    """
    pipeline_columns = {
        NEXT_EX_DATE: CashDividends.previous_ex_date.latest,
        PREVIOUS_EX_DATE: CashDividends.next_ex_date.latest,
        PREVIOUS_ANNOUNCEMENT: CashDividends.previous_announcement_date.latest,
        NEXT_PAY_DATE: CashDividends.next_pay_date.latest,
        PREVIOUS_PAY_DATE: CashDividends.previous_pay_date.latest,
        NEXT_AMOUNT: CashDividends.next_amount.latest,
        PREVIOUS_AMOUNT: CashDividends.previous_amount.latest,
        DAYS_SINCE_PREV_DIVIDEND_ANNOUNCEMENT:
            BusinessDaysSinceDividendAnnouncement(),
        DAYS_TO_NEXT_EX_DATE: BusinessDaysUntilNextExDate(),
        DAYS_SINCE_PREV_EX_DATE: BusinessDaysSincePreviousExDate()
    }

    event_dates_cases = [
        # K1--K2--E1--E2.
        pd.DataFrame({
            TS_FIELD_NAME: pd.to_datetime(['2014-01-05', '2014-01-10']),
            AD_FIELD_NAME: pd.to_datetime(['2014-01-15', '2014-01-20'])
        }),
        # K1--K2--E2--E1.
        pd.DataFrame({
            TS_FIELD_NAME: pd.to_datetime(['2014-01-05', '2014-01-10']),
            AD_FIELD_NAME: pd.to_datetime(['2014-01-20', '2014-01-15'])
        }),
        # K1--E1--K2--E2.
        pd.DataFrame({
            TS_FIELD_NAME: pd.to_datetime(['2014-01-05', '2014-01-15']),
            AD_FIELD_NAME: pd.to_datetime(['2014-01-10', '2014-01-20'])
        }),
        # K1 == K2.
        pd.DataFrame({
            TS_FIELD_NAME: pd.to_datetime(['2014-01-05'] * 2),
            AD_FIELD_NAME: pd.to_datetime(['2014-01-10', '2014-01-15'])
        }),
        pd.DataFrame({
            TS_FIELD_NAME: pd.to_datetime([]),
            AD_FIELD_NAME: pd.to_datetime([])
        })
    ]


    @classmethod
    def setUpClass(cls):
        cls._cleanup_stack = stack = ExitStack()
        equity_info = make_simple_equity_info(
            cls.sids,
            start_date=pd.Timestamp('2013-01-01', tz='UTC'),
            end_date=pd.Timestamp('2015-01-01', tz='UTC'),
        )
        cls.cols = {}
        cls.dataset = {sid: df for sid, df in enumerate(
            case.rename(
                columns={DATE_FIELD_NAME: ANNOUNCEMENT_FIELD_NAME}
            ) for case in cls.event_dates_cases)}
        cls.finder = stack.enter_context(
            tmp_asset_finder(equities=equity_info),
        )

        cls.loader_type = EarningsCalendarLoader

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_stack.close()

    def setup(self, dates):
        zip_with_floats_dates = partial(self.zip_with_floats, dates)
        num_days_between_dates = partial(self.num_days_between, dates)
        _expected_previous_announce = self.get_expected_previous_event_dates(
            dates
        )
        self.cols[PREVIOUS_ANNOUNCEMENT] = _expected_previous_announce
        _expected_next_ex_date = self.get_expected_previous_event_dates(dates)
        self.cols[NEXT_EX_DATE] = _expected_next_ex_date
        _expected_previous_ex_date = self.get_expected_previous_event_dates(
            dates
        )
        self.cols[PREVIOUS_EX_DATE] = _expected_previous_ex_date
        _expected_next_pay_date = self.get_expected_next_event_dates(dates)
        self.cols[NEXT_PAY_DATE] = _expected_next_pay_date
        _expected_previous_pay_date = self.get_expected_previous_event_dates(
            dates
        )
        self.cols[PREVIOUS_PAY_DATE] = _expected_previous_pay_date
        # TODO: fix amounts for next/previous to correct ones
        _expected_next_amount = pd.DataFrame({
            0: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-14') +
                [1] * num_days_between_dates('2014-01-15', '2014-01-19') +
                [15] * num_days_between_dates('2014-01-20', None)
            ),
            1: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-14') +
                [13] * num_days_between_dates('2014-01-15', '2014-01-19') +
                [7] * num_days_between_dates('2014-01-20', None)
            ),
            2: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-09') +
                [3] * num_days_between_dates('2014-01-10', '2014-01-19') +
                [1] * num_days_between_dates('2014-01-20', None)
            ),
            3: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-09') +
                [6] * num_days_between_dates('2014-01-10', '2014-01-14') +
                [23] * num_days_between_dates('2014-01-15', None)
            ),
            4: zip_with_floats_dates(['NaN'] * len(dates)),
        }, index=dates)
        self.cols[NEXT_AMOUNT] = _expected_next_amount
        _expected_previous_amount = pd.DataFrame({
            0: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-14') +
                [1] * num_days_between_dates('2014-01-15', '2014-01-19') +
                [15] * num_days_between_dates('2014-01-20', None)
            ),
            1: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-14') +
                [13] * num_days_between_dates('2014-01-15', '2014-01-19') +
                [7] * num_days_between_dates('2014-01-20', None)
            ),
            2: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-09') +
                [3] * num_days_between_dates('2014-01-10', '2014-01-19') +
                [1] * num_days_between_dates('2014-01-20', None)
            ),
            3: zip_with_floats_dates(
                ['NaN'] * num_days_between_dates(None, '2014-01-09') +
                [6] * num_days_between_dates('2014-01-10', '2014-01-14') +
                [23] * num_days_between_dates('2014-01-15', None)
            ),
            4: zip_with_floats_dates(['NaN'] * len(dates)),
        }, index=dates)
        self.cols[PREVIOUS_AMOUNT] = _expected_previous_amount
        _expected_days_since_prev_dividend_announcement =  \
            self._compute_busday_offsets(
                self.cols[PREVIOUS_ANNOUNCEMENT]
            )
        self.cols[DAYS_SINCE_PREV_DIVIDEND_ANNOUNCEMENT] = \
            _expected_days_since_prev_dividend_announcement
        _expected_days_to_next_ex_date =  \
            self._compute_busday_offsets(
                self.cols[DAYS_TO_NEXT_EX_DATE]
            )
        self.cols[DAYS_TO_NEXT_EX_DATE] = _expected_days_to_next_ex_date
        _expected_days_since_prev_ex_date =  \
            self._compute_busday_offsets(
                self.cols[DAYS_SINCE_PREV_EX_DATE]
            )
        self.cols[DAYS_SINCE_PREV_EX_DATE] = _expected_days_since_prev_ex_date


class BlazeEarningsCalendarLoaderTestCase(EarningsCalendarLoaderTestCase):
    @classmethod
    def setUpClass(cls):
        super(BlazeEarningsCalendarLoaderTestCase, cls).setUpClass()
        cls.loader_type = BlazeEarningsCalendarLoader

    def loader_args(self, dates):
        _, mapping = super(
            BlazeEarningsCalendarLoaderTestCase,
            self,
        ).loader_args(dates)
        return (bz.Data(pd.concat(
            pd.DataFrame({
                ANNOUNCEMENT_FIELD_NAME: df[ANNOUNCEMENT_FIELD_NAME],
                TS_FIELD_NAME: df[TS_FIELD_NAME],
                SID_FIELD_NAME: sid,
            })
            for sid, df in iteritems(mapping)
        ).reset_index(drop=True)),)


class BlazeEarningsCalendarLoaderNotInteractiveTestCase(
        BlazeEarningsCalendarLoaderTestCase):
    """Test case for passing a non-interactive symbol and a dict of resources.
    """
    @classmethod
    def setUpClass(cls):
        super(BlazeEarningsCalendarLoaderNotInteractiveTestCase,
              cls).setUpClass()
        cls.loader_type = BlazeEarningsCalendarLoader

    def loader_args(self, dates):
        (bound_expr,) = super(
            BlazeEarningsCalendarLoaderNotInteractiveTestCase,
            self,
        ).loader_args(dates)
        return swap_resources_into_scope(bound_expr, {})

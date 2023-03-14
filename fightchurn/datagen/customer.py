
from filelock import FileLock
from datetime import date, datetime, timedelta,time
from dateutil import relativedelta
from numpy import random
from random import randrange, randint
from math import ceil
import tempfile
import numpy as np
import pandas as pd
import os


class Customer:
    COMPLEX_PROPENSITY_SCALE=3.0
    AGE_SATISFACTION_SCALE = 0.5
    MIN_AGE = 12.0
    MAX_AGE = 82.0
    AGE_RANGE = MAX_AGE - MIN_AGE
    AVG_AGE = (MAX_AGE + MIN_AGE) / 2.0
    date_multipliers = {}
    ID_FILE = os.path.join(tempfile.gettempdir(), f'churn_customer_id.txt')
    ID_LOCK_FILE = os.path.join(tempfile.gettempdir(), f'churn_customer_id_lock.txt')

    def __init__(self,behavior_rates,satisfaction=None,channel_name='NA',start_of_month=None,country=None,complex_satisfaction=False):
        '''
        Creates a customer for simulation, given an ndarray of behavior rates, which are converted to daily.
        Each customer also has a unique integer id which will become the account_id in the database, and holds its
        own subscriptions and events.
        :param behavior_rates: ndarray of behavior rates, which are assumed to be PER MONTH
        '''
        with FileLock(Customer.ID_LOCK_FILE):
            next_id = 0
            if os.path.exists(Customer.ID_FILE):
                with open(Customer.ID_FILE, 'r') as id_file:
                    next_id = int(id_file.readline())
            self.id=next_id # set the id to the current class variable
            with open(Customer.ID_FILE, 'w') as id_file:
                id_file.write(f'{next_id+1}\n')
            if self.id % 100==0:
                print(f'Simulating customer {self.id}...')

        self.behavior_rates = behavior_rates
        self.behavior_rates['mean_value'] = None

        for valued_behavior in Customer.get_valued_behaviors(self.behavior_rates['behavior'].values):
            underlying_behavior = Customer.get_behavior_under_value(valued_behavior, self.behavior_rates['behavior'].values)
            uidx= self.behavior_rates['behavior']==underlying_behavior
            vidx= self.behavior_rates['behavior']==valued_behavior
            self.behavior_rates.loc[uidx,'mean_value']= self.behavior_rates.loc[vidx,'monthly_rate'].values[0]
            self.behavior_rates = self.behavior_rates.drop(self.behavior_rates[vidx].index,axis=0)

        if 'users' in behavior_rates['behavior'].values:
            bidx= self.behavior_rates['behavior'] == 'users'
            self.users = max(int( round(self.behavior_rates.loc[bidx,'monthly_rate'])),1)
            self.behavior_rates = self.behavior_rates.drop(self.behavior_rates[bidx].index,axis=0)
        else:
            self.users = None


        self.behavior_rates['daily_rate'] = (1.0/30.0)*self.behavior_rates['monthly_rate']
        self.channel=channel_name

        if start_of_month:
            self.age=random.uniform(Customer.MIN_AGE,Customer.MAX_AGE)
            self.date_of_birth = start_of_month + relativedelta.relativedelta(years=-int(self.age),
                                                                              months=-int( (self.age % 1)*12 ),
                                                                              days=-random.uniform(1,30))
        else:
            self.date_of_birth=None
            self.age = Customer.AVG_AGE

        self.country=country
        self.mrr=None
        self.base_mrr=None
        self.plan=None
        self.add_ons = pd.DataFrame()
        self.limits= {}
        age_contrib = Customer.AGE_SATISFACTION_SCALE * (Customer.AVG_AGE - self.age)/Customer.AGE_RANGE

        if not complex_satisfaction:
            if satisfaction is None:
                self.satisfaction_propensity = np.power(2.0, random.uniform(-1.5, 1.5) + age_contrib)
            else:
                self.satisfaction_propensity = satisfaction
            self.monetary_satisfaction=1.0
        else:
            nrand = len(self.behavior_rates)
            if self.users is not None:nrand = nrand+1
            if satisfaction is None:
                self.satisfaction_propensity = np.power(10.0, random.uniform(low=-Customer.COMPLEX_PROPENSITY_SCALE,
                                                                            high=Customer.COMPLEX_PROPENSITY_SCALE, size=nrand) + age_contrib)
            else:
                self.satisfaction_propensity = [satisfaction]*nrand
            self.monetary_satisfaction = np.power(10.0, random.uniform(-Customer.COMPLEX_PROPENSITY_SCALE, Customer.COMPLEX_PROPENSITY_SCALE) + age_contrib)

        self.subscriptions=[]
        self.events=[]

    def get_behavior_rate(self,behavior):
        if behavior == 'users':
            customer_rate = self.users
        elif behavior in self.behavior_rates['behavior'].values:
            customer_rate = self.behavior_rates[self.behavior_rates['behavior'] == behavior]['monthly_rate'].values[0]
        else:
            raise ValueError(f'get_behavior_rates UNKNOWN behavior {behavior}')
        return customer_rate

    @staticmethod
    def get_valued_behaviors(behavior_list):
        value_behaviors=[]
        for behave in behavior_list:
            if Customer.get_behavior_under_value(behave, behavior_list) is not None:
                value_behaviors.append(behave)
        return value_behaviors

    @staticmethod
    def get_underlying_behaviors(behavior_list):
        underlying_behaviors=[]
        for behave in behavior_list:
            if Customer.get_behavior_under_value(behave, behavior_list) is None:
                underlying_behaviors.append(behave)
        return underlying_behaviors

    @staticmethod
    def get_behavior_under_value(one_behavior, behavior_list):
        if not one_behavior.endswith('_value'):
            return None
        base_behave=str(one_behavior).replace('_value','')
        if base_behave in behavior_list:
            return base_behave
        else:
            return None

    def pick_initial_plan(self, plans, add_ons):
        choice_index = np.random.choice(range(len(plans)),p=plans['prob'])
        self.set_plan(plans,choice_index)
        if len(add_ons)>0:
            for add_on in add_ons.iterrows():
                if random.uniform(0,1) <= add_on[1]['prob']:
                    if len(self.add_ons)==0:
                        self.add_ons=pd.DataFrame([add_on[1]])
                    else:
                        self.add_ons=self.add_ons.append(add_on[1])
        self.add_add_ons(plans)


    def set_plan(self,plans,plan_idx=None, plan_name=None):
        if plan_idx is not None:
            self.plan = plans.index.values[plan_idx]
        else:
            self.plan = plan_name
        self.mrr = plans.loc[self.plan,'mrr']
        self.base_mrr = self.mrr
        if plans.shape[1]>2:
            self.limits = {
                behave : plans.loc[self.plan, behave] for behave in plans.columns[2:]
            }

    def add_add_ons(self,plans):
        # Reset to  base MRR
        self.set_plan(plans,plan_name=self.plan)
        for add_on in self.add_ons.iterrows():
            self.mrr+=add_on[1]['mrr']
            for limited in self.add_ons.columns[3:]:
                if limited in self.limits:
                    self.limits[limited]+= add_on[1][limited]
                else:
                    raise ValueError(f'Add on raises a limit {limited} that was not found')

    def generate_events(self,start_date,end_date):
        '''
        Generate a sequence of events at the customers daily rates.  Each count for an event on a day is droing from
        a poisson distribution with the customers average rate.  If the number is greater than zero, that number of events
        are created as tuples of time stamps and the event index (which is the database type id).  The time of the
        event is randomly set to anything on the 24 hour range.
        :param start_date: datetime.date for start of simulation
        :param end_date: datetime.date for end of simulation
        :return: The total count of each event, the list of all of the event tuples
        '''

        delta = end_date - start_date

        events=[]

        if self.users is None:
            counts=[0]*len(self.behavior_rates)
        else:
            counts=[0]*(len(self.behavior_rates)+1) # Plus one for number of users
        limit_counts = {b : 0 for b in self.limits.keys()}
        for i in range(delta.days):
            the_date = start_date + timedelta(days=i)
            # Set a multiplier for this date
            if the_date in Customer.date_multipliers:
                multiplier = Customer.date_multipliers[the_date]
            else:
                # TODO : should be an option
                if the_date.weekday() >= 4:
                    multiplier = random.uniform(1.00,1.2)
                else:
                    multiplier = random.uniform(0.825,1.025)
                Customer.date_multipliers[the_date]=multiplier

            if self.users is None:
                todays_users = 1
            else:
                todays_users = int(round(multiplier*random.poisson(self.users)))
                if 'users' in self.limits:
                    todays_users = min(todays_users,self.limits['users'])

            for row in  self.behavior_rates.iterrows():
                rate = row[1]['daily_rate']
                behavior_name = row[1]['behavior']
                new_count= int(round(multiplier*random.poisson(rate) * todays_users))
                if behavior_name in self.limits:
                    # print(new_count, self.limits, limit_counts)
                    new_count = min(new_count, self.limits[behavior_name]-limit_counts[behavior_name])
                    limit_counts[behavior_name]=limit_counts[behavior_name]+new_count

                for n in range(0,new_count):
                    event_time=datetime.combine(the_date,time(randrange(24),randrange(60),randrange(60)))
                    user_id = 0
                    if self.users is not None:
                        user_id = randint(0, todays_users-1)
                    if row[1]['mean_value'] is not None:
                        event_value = round(np.exp(np.random.normal(np.log(row[1]['mean_value']) )),2)
                        counts[row[0]] += event_value
                    else:
                        event_value = None
                        counts[row[0]] += 1
                    new_event=(event_time, row[0], user_id, event_value)
                    events.append(new_event )

            if self.users is not None:
                counts[-1] += todays_users

        if self.users is not None:
            counts[-1] = int(ceil( counts[-1]/delta.days)) # user count is returned as average, not total

        self.events.extend(events)

        return counts
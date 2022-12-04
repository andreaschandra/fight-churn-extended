
import pandas as pd
import numpy as np
from math import log, exp
from random import uniform
import os

from fightchurn.datagen.customer import Customer

class UtilityModel:

    def __init__(self,name):
        '''
        This class calculates the churn probability for a customer based on their event counts.  Its called a "Utility
        Model" to mean utility in the economic sense: How much a good or service to satisfies one or more needs or
        wants of a consumer. So how likely the customer is to churn depends on how much utility they get, which is
        based on how many events they have from the behavior model.

        The parameters of the utility model are loaded from a file.  The current implementation loads a file with the
        same form as the behavior model: a vector and a matrix.  The number of these must match the number of
        behaviors in the behavior model. The vector is for calculating multiplicative utility: Each element is multiplied
        by the number of events to get the model utility from those behaviors. The matrix is unused as of this time,
        but the idea was that a second term could be added with the matrix defining utility interactions between the
        behaviors. The utility is calculated in the function `utility_function`

        The churn probability is a sigmoidal function based on utility - see the function `simulate_churn`.

        :param name:
        :param churn_rate: Target churn rate for calibration
        :param behavior_model: The behavior model that this utility function works withy
        '''
        self.name=name
        local_dir = f'{os.path.abspath(os.path.dirname(__file__))}/conf/'
        data=pd.read_csv(local_dir + name+'_utility.csv',index_col=0)
        self.utility_weights=data['util']
        self.offset = self.utility_weights.loc['offset']
        self.mrr_utility_cost=self.utility_weights.loc['mrr']
        if self.mrr_utility_cost > 0:
            print(f"*** WARNING: MRR Should have a non-positive utility impact, but found {self.mrr_utility_cost}")
        self.utility_weights = self.utility_weights.drop(['offset','mrr'],axis=0)
        self.behave_names=self.utility_weights.index.values
        # Setup in setChurnScale,below
        self.behave_means = None
        self.behave_var = None
        self.expected_contributions = None
        self.expected_utility = None
        self.ex_util_vol = None
        self.kappa = None

    def setChurnScale(self,bemodDict,model_weights, plans):

        assert sum(model_weights['pcnt'])==1.0, "Model weights should sum to 1.0"
        n_behaviors = len(self.behave_names)
        self.behave_means = np.zeros((1,n_behaviors))
        self.behave_var = np.zeros((1,n_behaviors))

        for bemod in bemodDict.values():
            assert n_behaviors == len(bemod.behave_names)
            assert all(self.behave_names == bemod.behave_names)
            weight = model_weights.loc[bemod.version,'pcnt']
            self.behave_means = self.behave_means + weight * bemod.behave_means.values
            self.behave_var = self.behave_var + weight * bemod.behave_var()

        # pick the constant so the mean behavior has the target churn rate
        self.expected_contributions = self.behave_means * self.utility_weights.values
        temp_customer = Customer(self.behave_means, satisfaction=1.0)
        temp_customer.mrr = plans['mrr'].mean()
        self.ex_util_vol = np.sqrt(np.dot(self.behave_var, self.utility_weights.values))
        self.kappa = -1.0 / self.ex_util_vol

        # print('Churn={}, Retention={}, offset offset = {} [log(1.0/r-1.0) ]'.format(churn_fudge, r,log(1.0 / r - 1.0)))
        # print('Utility model expected util={}, util_vol={}'.format(self.expected_utility, self.ex_util_vol))
        # print('\tKappa={}, Offset={}'.format(self.kappa, self.offset))
        # expected_unscaled_prob = self.downgrade_probability(self.expected_utility)
        # print('\tExpected downgrade/churn prob={}'.format(expected_unscaled_prob))
        # if input("okay? (enter y to proceed) ") != 'y':
        #     exit(0)

    def utility_function(self,event_counts,customer):
        '''
        Given a vector of event_counts counts, calculate the model for customer utility.  Right now its just a dot
        product and doesn't use the matrix.  That can be added in the future to make more complex simulations.
        :param event_counts:
        :return:
        '''
        contrib_ratios = event_counts / self.behave_means
        utility_contribs = self.expected_contributions * (1.0 - np.exp(-2.0*contrib_ratios))
        utility = np.sum(utility_contribs)
        utility = utility + customer.mrr* self.mrr_utility_cost
        if customer.satisfaction_propensity != 1.0:
            multiplier = customer.satisfaction_propensity if utility > 0.0  else (1.0/customer.satisfaction_propensity)
        else:
            multiplier = 1.0
        utility *= multiplier
        return utility

    def churn_probability(self,u):

        churn_prob=1.0-1.0/(1.0+exp(self.kappa*u + self.offset))

        return churn_prob

    def downgrade_probability(self,u):
        down_prob=1.0-1.0/(1.0+exp(self.kappa*u*2 + self.offset+0.5))
        return down_prob


    def uprade_probability(self,u):
        # up_prob=1.0/(1.0+exp(self.kappa*u*2 + self.offset+6))
        up_prob=1.0/(1.0+exp(self.kappa*u*0.5 + self.offset+7.5))
        return up_prob

    def simulate_churn(self,event_counts,customer):
        '''
        Simulates one customer churn, given a set of event counts.  The retention probability is a sigmoidal function
        in the utility, and the churn probability is 100% minus retention. The return value is a binary indicating
        churn or no churn, by comparing a uniform random variable on [0,1] to the churn probability.
        :param event_counts:
        :return:
        '''
        utility = self.utility_function(event_counts,customer)
        return uniform(0, 1) < self.churn_probability(utility)

    def simulate_upgrade_downgrade(self,event_counts,customer,plans):
        current_plan = plans.loc[plans['mrr']==customer.mrr].index[0]
        u=self.utility_function(event_counts,customer)
        upgrade_probability = self.uprade_probability(u)
        downgrade_probability = self.downgrade_probability(u)
        # churn_probability = self.churn_probability(u)
        # print(f'u={u}, c={churn_probability}, up={upgrade_probability}, down={downgrade_probability}')

        if current_plan < plans.shape[0]-1:
            if uniform(0, 1) < upgrade_probability:
                new_plan = current_plan+1
                customer.mrr = plans['mrr'].loc[new_plan]
        elif current_plan > 0:
            if uniform(0, 1) < downgrade_probability:
                new_plan = current_plan-1
                customer.mrr = plans['mrr'].loc[new_plan]

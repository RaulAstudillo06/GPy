# Copyright (c) 2013, GPy Authors, see AUTHORS.txt
# Licensed under the BSD 3-clause license (see LICENSE.txt)

from kernpart import Kernpart
import numpy as np
from GPy.util.linalg import mdot, pdinv
from GPy.util.ln_diff_erfs import ln_diff_erfs
import pdb
from scipy import weave

class Eq_ode1(Kernpart):
    """
    Covariance function for first order differential equation driven by an exponentiated quadratic covariance.

    This outputs of this kernel have the form
    .. math::
       \frac{\text{d}y_j}{\text{d}t} = \sum_{i=1}^R w_{j,i} f_i(t-\delta_j) +\sqrt{\kappa_j}g_j(t) - d_jy_j(t)

    where :math:`R` is the rank of the system, :math:`w_{j,i}` is the sensitivity of the :math:`j`th output to the :math:`i`th latent function, :math:`d_j` is the decay rate of the :math:`j`th output and :math:`f_i(t)` and :math:`g_i(t)` are independent latent Gaussian processes goverened by an exponentiated quadratic covariance.
    
    :param output_dim: number of outputs driven by latent function.
    :type output_dim: int
    :param W: sensitivities of each output to the latent driving function. 
    :type W: ndarray (output_dim x rank).
    :param rank: If rank is greater than 1 then there are assumed to be a total of rank latent forces independently driving the system, each with identical covariance.
    :type rank: int
    :param decay: decay rates for the first order system. 
    :type decay: array of length output_dim.
    :param delay: delay between latent force and output response.
    :type delay: array of length output_dim.
    :param kappa: diagonal term that allows each latent output to have an independent component to the response.
    :type kappa: array of length output_dim.
    
    .. Note: see first order differential equation examples in GPy.examples.regression for some usage.
    """
    def __init__(self,output_dim, W=None, rank=1, kappa=None, lengthscale=1.0,  decay=None, delay=None):
        self.rank = rank
        self.input_dim = 1
        self.name = 'eq_ode1'
        self.output_dim = output_dim
        self.lengthscale = lengthscale
        self.num_params = self.output_dim*(1. + self.rank) + 1
        if kappa is not None:
            self.num_params+=self.output_dim
        if delay is not None:
            self.num_params+=self.output_dim
        self.rank = rank
        if W is None:
            self.W = 0.5*np.random.randn(self.output_dim,self.rank)/np.sqrt(self.rank)
        else:
            assert W.shape==(self.output_dim,self.rank)
            self.W = W
        if decay is None:
            self.decay = np.ones(self.output_dim)
        if kappa is not None:
            assert kappa.shape==(self.output_dim,)
        self.kappa = kappa

        if delay is not None:
            assert delay.shape==(self.output_dim,)
        self.delay = delay
        self.is_normalized = True
        self.is_stationary = False
        self._set_params(self._get_params())

    def _get_params(self):
        param_list = [self.W.flatten()]
        if self.kappa is not None:
            param_list.append(self.kappa)
        param_list.append(self.decay)
        if self.delay is not None:
            param_list.append(self.delay)
        param_list.append(self.lengthscale)
        return np.hstack(param_list)

    def _set_params(self,x):
        assert x.size == self.num_params
        end = self.output_dim*self.rank
        self.W = x[:end].reshape(self.output_dim,self.rank)
        start = end
        self.B = np.dot(self.W,self.W.T)
        if self.kappa is not None:
            end+=self.output_dim
            self.kappa = x[start:end]
            self.B += np.diag(self.kappa)
            start=end
        end+=self.output_dim
        self.decay = x[start:end]
        start=end
        if self.delay is not None:
            end+=self.output_dim
            self.delay = x[start:end]
            start=end
        end+=1
        self.lengthscale = x[start]
        self.sigma = np.sqrt(2)*self.lengthscale


    def _get_param_names(self):
        param_names = sum([['W%i_%i'%(i,j) for j in range(self.rank)] for i in range(self.output_dim)],[])
        if self.kappa is not None:
            param_names += ['kappa_%i'%i for i in range(self.output_dim)]
        param_names += ['decay_%i'%i for i in range(self.output_dim)]
        if self.delay is not None:
            param_names += ['delay_%i'%i for i in range(self.output_dim)]
        param_names+= ['lengthscale'] 
        return param_names

    def K(self,X,X2,target):
        
        if X.shape[1] > 2:
            raise ValueError('Input matrix for ode1 covariance should have at most two columns, one containing times, the other output indices')

        self._K_computations(X, X2)
        target += self._scales*self._dK_dvar

        if self.gaussian_initial:
            # Add covariance associated with initial condition.
            t1_mat = self._t[self._rorder, None]
            t2_mat = self._t2[None, self._rorder2]
            target+=self.initial_variance * np.exp(- self.decay * (t1_mat + t2_mat))



    def Kdiag(self,index,target):
        #target += np.diag(self.B)[np.asarray(index,dtype=np.int).flatten()]
        pass
    
    def dK_dtheta(self,dL_dK,index,index2,target):
        pass

    def dKdiag_dtheta(self,dL_dKdiag,index,target):
        pass

    def dK_dX(self,dL_dK,X,X2,target):
        pass

    def _extract_t_indices(self, X, X2=None):
        """Extract times and output indices from the input matrix X. Times are ordered according to their index for convenience of computation, this ordering is stored in self._order and self.order2. These orderings are then mapped back to the original ordering (in X) using self._rorder and self._rorder2. """

        # TODO: some fast checking here to see if this needs recomputing?
        self._t = X[:, 0]
        if X.shape[1]==1:
            # No index passed, assume single output of ode model.
            self._index = np.ones_like(X[:, 1],dtype=np.int)
        self._index = np.asarray(X[:, 1],dtype=np.int)
        # Sort indices so that outputs are in blocks for computational
        # convenience.
        self._order = self._index.argsort()
        self._index = self._index[self._order]
        self._t = self._t[self._order]
        self._rorder = self._order.argsort() # rorder is for reversing the order
        
        if X2 is None:
            self._t2 = None
            self._index2 = None
            self._rorder2 = self._rorder
        else:
            if X2.shape[1] > 2:
                raise ValueError('Input matrix for ode1 covariance should have at most two columns, one containing times, the other output indices')
            self._t2 = X2[:, 0]
            if X.shape[1]==1:
                # No index passed, assume single output of ode model.
                self._index2 = np.ones_like(X2[:, 1],dtype=np.int)
            self._index2 = np.asarray(X2[:, 1],dtype=np.int)
            self._order2 = self._index2.argsort()
            slef._index2 = self._index2[self._order2]
            self._t2 = self._t2[self._order2]
            self._rorder2 = self._order2.argsort() # rorder2 is for reversing order

    def _K_computations(self, X, X2):
        """Perform main body of computations for the ode1 covariance function."""
        # First extract times and indices.
        self._extract_t_indices(X, X2)

        self._K_compute_eq()
        self._K_compute_ode_eq()
        if X2 is None:
            self._K_eq_ode = self._K_ode_eq.T
        else:
            self._K_compute_ode_eq(transpose=True)
        self._K_compute_ode()
        
        # Reorder values of blocks for placing back into _K_dvar.
        self._K_dvar[self._rorder, :] = np.vstack((np.hstack((self._K_eq, self._Keq_ode)),
                                                   np.hstack((self._K_ode_eq, self.K_ode))))[:, self._rorder2]


    def _K_compute_eq(self):
        """Compute covariance for latent covariance."""
        t_eq = self._t[self._index==0]
        if t_eq.shape[0]==0:
            self._K_eq = np.zeros((0, 0))
            return
        
        if self._t2 is None:
            self._dist2 = np.square(t_eq[:, None] - t_eq[None, :])
        else:
            t2_eq = self._t2[self._index2==0]
            if t2_eq.shape[0]==0:
                self._K_eq_eq = np.zeros((0, 0))
                return
            self._dist2 = np.square(t_eq[:, None] - t2_eq[None, :])
        
        self._K_eq = np.exp(-self._dist2/(2*self.lengthscale*self.lengthscale))
        if self.is_normalized:
            self._K_eq/=(np.sqrt(2*np.pi)*self.lengthscale)

    def _K_compute_ode_eq(self, transpose=False):
        """Compute the cross covariances between latent exponentiated quadratic and observed ordinary differential equations.

        :param transpose: if set to false the exponentiated quadratic is on the rows of the matrix and is computed according to self._t, if set to true it is on the columns and is computed according to self._t2 (default=False).
        :type transpose: bool"""

        if transpose:
            if self._t2 is not None:
                t_ode = self._t2[self._index2>0]
                index_ode = self._index2[self._index2>0]-1
                if t_ode.shape[0]==0:
                    self._K_eq_ode = np.zeros((0, 0))
                    return
            else:
                self._K_eq_ode = np.zeros((0, 0))
                return
        
            t_eq = self._t[self._index==0]
            if t_eq.shape[0]==0:
                self._K_eq_ode = np.zeros((0, 0))
                return
        else:
            t_ode = self._t[self._index>0]
            index_ode = self._index[self._index>0]-1
            if t_ode.shape[0]==0:
                self._K_ode_eq = np.zeros((0, 0))
                return
            if self._t2 is not None:            
                t_eq = self._t2[self._index2==0]
                if t_eq.shape[0]==0:
                    self._K_ode_eq = np.zeros((0, 0))
                    return
            else:
                self._K_ode_eq = np.zeros((0, 0))
                return
        # Matrix giving scales of each output
        # self._scale = np.zeros((t_ode.shape[0], t_eq.shape[0]))
        # code="""
        #     for(int i=0;i<N; i++){
        #       for(int j=0; j<N2; j++){
        #           scale_mat[i+j*N] = W[index_ode[i]+index_eq[j]*output_dim];
        #         }
        #       }
        #     """
        #     scale_mat, B = self._scale, self._B
        #     N, N2, output_dim = index_ode.size, index_eq.size, self.output_dim
        #     weave.inline(code,['index_ode', 'index_eq',
        #                        'scale_mat', 'B',
        #                        'N', 'N2', 'output_dim'])
        # else:
        #     self._scale = np.zeros((t_ode.shape[0], t2_ode.shape[0]))
        #     code = """
        #     for(int i=0; i<N; i++){
        #       for(int j=0; j<N2; j++){
        #         scale_mat[i+j*N] = B[index_ode[i]+output_dim*index2_ode[j]]
        #       }
        #     }
        #     """
        #     scale_mat, B = self._scale, self._B
        #     N, N2, output_dim = index_ode.size, index2.size, self.output_dim
        #     weave.inline(code, ['index_ode', 'index2_ode',
        #                         'scale_mat', 'B',
        #                         'N', 'N2', 'output_dim'])
        t_ode_mat = t_ode[:, None]
        t_eq_mat = t_eq[None, :]
        if self.delay is not None:
            t_ode_mat -= self.delay[index_ode, None]
        diff_t = (t_ode_mat - t_eq_mat)

        inv_sigma_diff_t = 1./self.sigma*diff_t
        half_sigma_d_i = 0.5*self.sigma*self.decay

        if self.is_stationary == False:
            ln_part, signs = ln_diff_erfs(half_sigma_d_i + t_eq_mat/sigma, half_sigma_d_i - inv_sigma_diff_t, return_sign=True)
        else:
            ln_part, signs = ln_diff_erfs(inf, half_sigma_d_i - inv_sigma_diff_t, return_sign=True)
        sK = signs*exp(half_sigma_d_i*half_sigma_d_i - self.decay*diff_t + ln_part)

        sK *= 0.5

        if not self.is_normalized:
            sK *= sqrt(pi)*self.sigma


        if transpose:
            self._K_eq_ode = sK.T
        else:
            self._K_ode_eq = sK
        return K
        
    def _K_compute_ode(self):
        # Compute covariances between outputs of the ODE models.

        t_ode = self._t[self._index>0]
        index_ode = self._index[self._index>0]-1
        if t_ode.shape[0]==0:
            self._K_ode = np.zeros((0, 0))
            return
        
        if self._t2 is None:
            t2_ode = t_ode
            index2_ode = index_ode
        else:
            t2_ode = self._t2[self._index2>0]
            index2_ode = self._index2[self._index2>0]-1
            if t2_eq.shape[0]==0:
                self._K_ode = np.zeros((0, 0))
                return
        
        if self._index2 is None:
            # Matrix giving scales of each output
            self._scale = np.zeros((t_ode.shape[0], t_ode.shape[0]))
            code="""
            for(int i=0;i<N; i++){
              scale_mat[i+i*N] = B[index_ode[i]+output_dim*(index_ode[i])];
              for(int j=0; j<i; j++){
                  scale_mat[j+i*N] = B[index_ode[i]+output_dim*index_ode[j]];
                  scale_mat[i+j*N] = scale_mat[j+i*N];
                }
              }
            """
            scale_mat, B = self._scale, self.B
            N, output_dim = index_ode.size, self.output_dim
            weave.inline(code,['index_ode',
                               'scale_mat', 'B',
                               'N', 'output_dim'])
        else:
            self._scale = np.zeros((t_ode.shape[0], t2_ode.shape[0]))
            code = """
            for(int i=0; i<N; i++){
              for(int j=0; j<N2; j++){
                scale_mat[i+j*N] = B[index_ode[i]+output_dim*index2_ode[j]]
              }
            }
            """
            scale_mat, B = self._scale, self.B
            N, N2, output_dim = index_ode.size, index2.size, self.output_dim
            weave.inline(code, ['index_ode', 'index2_ode',
                                'scale_mat', 'B',
                                'N', 'N2', 'output_dim'])
        
        # When index is identical
        if self.is_stationary:
            h = self._compute_H_stat(t_ode, index_ode, t2_ode, index2_ode)
        else:
            h = self._compute_H(t_ode, index_ode, t2_ode, index2_ode)

        if self._t2 is None:
            self._K_ode = 0.5 * (h + h.T)
        else:
            if self.is_stationary:
                h2 = self._compute_H_stat(t2_ode, index2_ode, t_ode, index_ode)
            else:
                h2 = self._compute_H(t2_ode, index2_ode, t_ode, index_ode)                
            self._K_ode += 0.5 * (h + h2.T)

        if not self.is_normalized:
            self._K_ode *= np.sqrt(np.pi)*sigma
    
    def _compute_H(self, t, index, t2, index2, update_derivatives=False):
        """Helper function for computing part of the ode1 covariance function.

        :param t: first time input.
        :type t: array
        :param index: Indices of first output.
        :type index: array of int
        :param t2: second time input.
        :type t2: array
        :param index2: Indices of second output.
        :type index2: array of int
        :param update_derivatives: whether to update derivatives (default is False)
        :return h : result of this subcomponent of the kernel for the given values.
        :rtype: ndarray
"""


        # Vector of decays and delays associated with each output.
        Decay = np.zeros(t.shape[0])
        Decay2 = np.zeros(t2.shape[0])
        Delay = np.zeros(t.shape[0])
        Delay2 = np.zeros(t2.shape[0])
        code="""
        for(int i=0;i<N; i++){
          Decay[i] = decay[index[i]];
          }
        for(int i=0; i<N2; i++){
          Decay2[i] = decay[index2[i]];
          }
        """
        decay = self.decay
        N, N2 = index.size, index2.size
        weave.inline(code,['index', 'index2',
                           'Decay', 'Decay2',
                           'decay',
                           'N', 'N2'])
        t_mat = t[:, None]
        t2_mat = t2[None, :]
        if self.delay is not None:
            code="""
            for(int i=0;i<N; i++){
              Delay[i] = delay[index[i]];
              }
            for(int i=0; i<N2; i++){
              Delay2[i] = delay[index2[i]];
              }
            """
            delay=self.delay
            N, N2 = index.size, index2.size
            weave.inline(code,['index', 'index2',
                               'Delay', 'Delay2', 
                               'delay', 
                               'N', 'N2'])

            t_mat-=Delay[:, None]
            t2_mat-=Delay2[None, :]

        diff_t = (t_mat - t2_mat)
        inv_sigma_diff_t = 1./self.sigma*diff_t
        half_sigma_decay_i = 0.5*self.sigma*Decay[:, None]

        ln_part_1, sign1 = ln_diff_erfs(half_sigma_decay_i + t2_mat/self.sigma, 
                                        half_sigma_decay_i - inv_sigma_diff_t,
                                        return_sign=True)
        ln_part_2, sign2 = ln_diff_erfs(half_sigma_decay_i,
                                        half_sigma_decay_i - t_mat/self.sigma,
                                        return_sign=True)

        h = sign1*np.exp(half_sigma_decay_i
                         *half_sigma_decay_i
                         -Decay[:, None]*diff_t+ln_part_1
                         -np.log(Decay[:, None] + Decay2[None, :]))
        h -= sign2*np.exp(half_sigma_decay_i*half_sigma_decay_i
                          -Decay[:, None]*t_mat-Decay2[None, :]*t2_mat+ln_part_2
                          -np.log(Decay[:, None] + Decay2[None, :]))


        # if update_derivatives:
        #     sigma2 = self.sigma*self.sigma
        #     # Update ith decay gradient
        #     dh_ddecay += (0.5*self.decay[i]*sigma2*(self.decay[i] + decay[j])-1)*h
        #     + (-diff_t*sign1*np.exp(half_sigma_decay_i*half_sigma_decay_i-self.decay[i]*diff_t+ln_part_1) 
        #        +t_mat*sign2*np.exp(half_sigma_decay_i*half_sigma_decay_i-self.decay[i]*t_mat - decay[j]*t2_mat+ln_part_2)) ...
        #     +self.sigma/sqrt(pi)*(-np.exp(-diff_t*diff_t/sigma2)
        #                           +np.exp(-t2_mat*t2_mat/sigma2-self.decay[i]*t_mat) 
        #                           +np.exp(-t_mat*t_mat/sigma2-decay[j]*t2_mat) ...
        #                           -np.exp(-(self.decay[i]*t_mat + decay[j]*t2_mat)))
        #     self._dh_ddecay[i] += real(dh_ddecay/(self.decay[i]+decay[j]))

        #     # Update jth decay gradient
        #     dh_ddecay = t2_mat*sign2*np.exp(half_sigma_decay_i*half_sigma_decay_i-(self.decay[i]*t_mat + decay[j]*t2_mat)+ln_part_2)-h
        #     self._dh_ddecay[j] += real(dh_ddecay/(self.decay[i] + decay[j]))
            
        #     # Update sigma gradient
        #     self._dh_dsigma += 0.5*self.decay[i]*self.decay[i]*self.sigma*h + 2/(np.sqrt(np.pi)*(self.decay[i]+decay[j]))*((-diff_t/sigma2-self.decay[i]/ 
        #                                                                                                                     2)*np.exp(-diff_t*
        #                                                                                                                               diff_t/sigma2) 
        #                                                                                                                    + (-t2_mat/sigma2+self.decay[i]/2)
        #                                                                                                                    *np.exp(-t2_mat*t2_mat/sigma2 
        #                                                                                                                            -self.decay[i]*t_mat) 
        #                                                                                                                    - (-t_mat/sigma2-self.decay[i]/2) 
        #                                                                                                                    *np.exp(-t_mat*t_mat/sigma2-decay[j]*t2_mat) 
        #                                                                                                                    - self.decay[i]/2*np.exp(-(self.decay[i]*t_mat+decay[j]*t2_mat)))
                

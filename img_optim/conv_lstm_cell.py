import torch
import math
import torch.nn as nn
from torch.nn import Parameter
# GOAL: Reproduce results on sequential MNIST

# Pseudo-code at https://arxiv.org/abs/1506.04214
"""
References:
[1] https://github.com/ndrplz/ConvLSTM_pytorch/blob/master/convlstm.py
[2] https://github.com/aserdega/convlstmgru/blob/master/convlstm.py (Implements Peepholes, CUDA)

My contribution is proper implemetation of bias parameters and subConvLSTM
Default behavior is set to Lotter et al. (can be adjusted to replicate Xingjian et al. 2015)
"""

def hard_sigmoid(input):
	"""
	hard_sigmoid:
	Implementation of simgoid linear approx.

	Arguments
	---------

	input: Tensor
	"""
	lower = torch.tensor(0.0).cuda()
	upper = torch.tensor(1.0).cuda()
	return torch.max(torch.min(input*0.2 + 0.5, upper), lower)

class ConvLSTMCell(nn.Module):
	def __init__(self, input_size, input_dim, hidden_dim, kernel_size, gating_mode='mul', 
				 peephole=False, tied_bias=False):

		"""
		ConvLSTMCell:

		Implementation of a single Convolutional LSTM cell

		Arguments
		---------

		input_size: (int, int)
			Image size (height, width)
		input_dim: int
			dim of input tensor
		hidden_dim: int
			dim of ouptut/hidde/cell tensor (number of kernels/channels)
		kernel_size: (int, int)
			dims of kernel
		gating_mode: str
			['mul', 'sub']
		peephole: boolean
			To include/exclude peephole connections
		tied_bias: optional, boolean
			toggle between tied vs untied bias weights for Conv2d

		Example
		-------
		>> model =  ConvLSTMCell(3, 2, (3,3), bias =False)

		"""

		super(ConvLSTMCell, self).__init__()

		# Convolution hyper-parameters
		self.gating_mode = gating_mode
		self.peephole = peephole
		self.tied_bias = tied_bias

		self.input_size = input_size # used for peephole connections
		self.input_dim = input_dim # color channels in input (# of kernels in prev layer)
		self.hidden_dim = hidden_dim # of kernels in current layer
		self.kernel_size = kernel_size
		# Compatible with python 2.7
		self.padding = tuple(k // 2 for k in self.kernel_size)
		# Below works for python 3.6 
		# self.padding = 'same' # height x width of hidden state is determined by padding
		self.kern_names = ["Wxi", "Whi", "Wxf", "Whf", "Wxo", "Who", "Wxc", "Whc"]
		self.peep_names = ["Wci", "Wcf", "Wco"]
		self.tied_bias_names = ["bi", "bf", "bc", "bo"]

		'''
		Input gate params:, Wxi, Whi, Wci

		Forget gate params: Wxf, Whf, Wcf

		Output gate params: Wxo, Who, Wco

		Candidate: Wxc, Whc
		'''

		for kern_n in self.kern_names:
			if 'x' in kern_n: # kernels that convolve input Xt
				self.__setattr__(kern_n, nn.Conv2d(self.input_dim, self.hidden_dim, self.kernel_size, 1,
								self.padding, bias= not self.tied_bias))
			else: # kernels that convovel Ht or Ct
				self.__setattr__(kern_n, nn.Conv2d(self.hidden_dim, self.hidden_dim, self.kernel_size, 1,
								self.padding, bias= not self.tied_bias))

		for peep_n in self.peep_names:
			self.register_parameter(peep_n, Parameter(torch.ones(self.hidden_dim, *self.input_size, requires_grad=self.peephole)))


		for bias in self.tied_bias_names:
			# a scalar (tied) bias for each kern
			self.register_parameter(bias, Parameter(torch.zeros((hidden_dim,1,1), requires_grad=self.tied_bias)))
	
	def forward(self, input_tensor, prev_state): # arXiv:1506.04214
		"""
		forward:

		Pass a time-point through ConvLSTM cell

		Arguments
		---------

		input_tensor: 4D Tensor
			Xt Dims: (N, C, H, W)
		prev_state: (4D Tensor, 4D Tensor)
			(Ht, Ct)

		"""

		Xt = input_tensor
		Htm1, Ctm1 = prev_state

		#----------- DEBUGGING -----------------
		'''
		t1 = self.Wxi(Xt)
		t2 = self.Whi(Htm1)

		print('Wci:', self.Wci.shape)
		print('Ctm1:', Ctm1.shape)
		print('Htm1:', Htm1.shape)

		batch_sz = Htm1.size(0)
		H, C = self.init_hidden(batch_sz)
		print('C:', C.shape)
		print('H:', H.shape)

		t3 = self.Wci * Ctm1
		'''

		#----------- END DEBUG ----------------

		# TODO: Try nn.HardSigmoid() as per Lotter et al.
		# Original calls sigmoid
		# Pytorch 1.4.0 does not have hardsigmoid

		i = hard_sigmoid(self.Wxi(Xt) + self.Whi(Htm1)  + self.Wci * Ctm1 + self.bi)
		f = hard_sigmoid(self.Wxf(Xt) + self.Whf(Htm1) + self.Wcf * Ctm1 + self.bf)
		if self.gating_mode == 'mul':
			Ct_ = torch.tanh(self.Wxc(Xt) + self.Whc(Htm1) + self.bc) # candidate for new cell state
			Ct = f * Ctm1 + i * Ct_
			o = hard_sigmoid(self.Wxo(Xt) + self.Who(Htm1) + self.Wco * Ct + self.bo)
			Ht = o * torch.tanh(Ct)
		else:
			Ct_ = hard_sigmoid(self.Wxc(Xt) + self.Whc(Htm1) + self.bc) # candidate for new cell state
			Ct = f * Ctm1 + Ct_ - i
			o = hard_sigmoid(self.Wxo(Xt) + self.Who(Htm1) + self.Wco * Ct + self.bo)
			Ht = hard_sigmoid(Ct) - o

		return (Ht, Ct)
    
	def init_hidden(self, batch_size):
		"""
		init_hidden:

		Initializes Ht and Ct

		Arguments
		---------

		batch_size: int
			number of samples before weight update OR
			number of sequences that are trained together OR
			number of predictions each time step

		"""

		device_ = self.Wxi.weight.device
		h, w = self.input_size
		return (torch.zeros((batch_size, self.hidden_dim, h, w), device = device_),
				torch.zeros((batch_size, self.hidden_dim, h, w), device = device_))

if __name__ == "__main__":
	# Dimensions
	'''
	PRO TIP: Create a new model that shares same 
	parameters but has batch_sz=1 for next frame prediciton
	'''
	batch_sz = 10
	in_dim = 3
	hid_dim = 2
	kern_sz = (5,5)
	in_sz = (120, 160) #(160,120)

	# Given a single batch of Xt (hence no sequence dim)
	h, w = in_sz
	x = torch.rand(size=(batch_sz, in_dim, h, w)) 
	model =  ConvLSTMCell(in_sz, in_dim, hid_dim, kern_sz, tied_bias=True, peep_hole=True)
	Htm1, Ctm1 = model.init_hidden(batch_sz)
	Ht, Ct = model(x, (Htm1, Ctm1))
	#print(Ht, Ct)


#!/usr/bin/env	python2.7

import re, math, os, sys, operator, random
import networkx as nx
from collections import defaultdict

def parseLST(file):

	lst = []
	fh = open(file, 'r')
	for line in fh:
		line = line.rstrip()
		lst.append(line)

	return lst

def transpose(data):
	"""
	Take a dict[index_A][index_B] and reverse items so it's
	indexed dict[index_B][index_A]
	"""
	data_t = {}
	for idx_A in data:
		for idx_B in data[idx_A]:
			if idx_B not in data_t:
				data_t[idx_B] = {}
			data_t[idx_B][idx_A] = data[idx_A][idx_B]
			
	return data_t

def parseHeats(file, network_nodes=None):
	"""
	Parse input heats file in form:
		<gene> <heat> <perturbation/activity sign (+/-)>
		
	Returns:
		- Two hashes: one indexing by gene and storing the input heats, and one storing the input signs
	"""
	
	heats = {}
	signs = {}
	fh = None
	try:
		fh = open(file, 'r')
	except:
		raise Exception("Error: can't open file: "+file)

	lineno = 1
	for line in fh:
		parts = line.rstrip().split("\t")
		if len(parts) > 2:
			prot, heat, sign = line.rstrip().split("\t")

			# provide a warning if node not in the network
			if network_nodes and prot not in network_nodes:
				sys.stderr.write("Warning: input heat node "+prot+" not in the network and will be ignored...\n")
				continue

			# input validation for heat values
			try:
				heats[prot] = float(heat)
			except:
				raise Exception("Error: non float heat value on line "+str(lineno)+" gene "+prot)

			# input validation for input signs
			if sign != "+" and sign != "-":
				raise Exception("Error: invalid value for heat sign on line "+str(lineno)+sign)

			signs[prot] = sign
		else:
			heats[parts[0]] = float(parts[1])

		lineno += 1

	fh.close()
	return (heats, signs)

def edgelist2nodes(list):
	"""
	Input:
		A list of edges in (source, interaction, target) string form.

	Returns:
		A set object of nodes in the input network

	>>> edgelist2nodes([("A","i>","B"),("B","-a>","C")])
	set(['A', 'C', 'B'])
	"""

	nodes = set()
	for (source, i, target) in list:
		nodes.add(source)
		nodes.add(target)

	return nodes
	
def classifyInteraction(i):
	"""
	
	Returns the edge activation type (-1,0,1), and the textual description

	>>> classifyInteraction("component>")
	(0, 'component')
	>>> classifyInteraction("-a>")
	(1, 'a')
	>>> classifyInteraction("-t>")
	(1, 't')
	>>> classifyInteraction("-t|")
	(-1, 't')
	>>> classifyInteraction("-a|")
	(-1, 'a')
	>>> classifyInteraction("HPRD>")
	(1, 'INTERACTS')
	>>> classifyInteraction("REWIRED>")
	(1, 'REWIRED')
	"""
	componentRE = re.compile("^-?component>$")
	activatingRE = re.compile("^-?(\S)>$")
	inactivatingRE = re.compile("^-?(\S)\|$")
	rewiredAC = re.compile("^-?REWIRED>$")
	rewiredIN = re.compile("^-?REWIRED\|$")
	
	if componentRE.match(i):
		return (0, "component")
	elif activatingRE.match(i):
		type = activatingRE.match(i)
		return (1, type.group(1))
	elif inactivatingRE.match(i):
		type = inactivatingRE.match(i)
		return (-1, type.group(1))
	elif rewiredAC.match(i):
		type = "REWIRED"
		return (1, type)
	elif rewiredIN.match(i):
		type = "REWIRED"
		return (-1, type)
	else:
		# default to activating links for HPRD or other protein
		# component links. These are bi-directional
		return (1, "INTERACTS")

def getOutDegrees(network):
	"""
	Get the out-degree of each node in the network

	Input:
		network:
			{ [source]: (interaction, target) }

	Returns:
		a hash of node out-degrees

	>>> network = {}
	>>> network['S1'] = set()
	>>> network['S2'] = set()
	>>> network['T1'] = set()
	>>> network['S1'].add(('a>','T1'))
	>>> network['S2'].add(('a>','T2'))
	>>> network['S2'].add(('a|','T3'))
	>>> network['T1'].add(('t|','T2'))
	>>> getOutDegrees(network)
	{'S2': 2, 'S1': 1, 'T2': 0, 'T3': 0, 'T1': 1}

	"""
	outDegrees = {}
	for s in network:
		outDegrees[s] = len(network[s]) 
		for (i, t) in network[s]:
			if t not in outDegrees:
				outDegrees[t] = 0

	return outDegrees
	
def edges2degrees(edges):
	"""
	Takes simple edges in (source, target) format, and returns a hash of the 
	total degree of each node.

	>>> edges2degrees([("A","B"),("B","C")])
	{'A': 1, 'C': 1, 'B': 2}
	"""

	nodes = {}
	for (s,t) in edges:
		if s not in nodes:
			nodes[s] = {}
		if t not in nodes:
			nodes[t] = {}

		nodes[s][t] = 1
		nodes[t][s] = 1

	sizes = {}	
	for n in nodes:
		sizes[n] = len(nodes[n])

	return sizes

def isRewired(i):
	rewiredRE = re.compile(".*REWIRED.*")
	rewiredComponentRE = re.compile(".*\-component.*")

	if rewiredRE.match(i):
		return True
	elif rewiredComponentRE.match(i):
		return True

	return False

# do a depth-first search by following directional links 
# until we hit another source
# find edges 
def searchDFS(source, action, discovered, linker_nodes, target_set, net, gene_states, transcriptional_signs, depth, truePaths, falsePaths, falsePathStatus):
	'''
	Perform a depth-first search by following directional links 
	until we hit another source. Validate link interactions along the way. 
	Recursive calls. 

	Input:
		source: source node by name
		action: +1/-1 binary action
		discovered: store validated 'discovered' paths
		linker_nodes: build the list of linker nodes as we recurse through the function. Add them to validation
		list if they lead to a known target
		net: network in hash-format {'source':(interaction, target), ...}
		gene_states: hash of 'action' states for each gene in the network
		transcriptional_signs: equivalent to 'gene_states' for transcriptionally active nodes
		depth: level of recursion (stop if it hits zero)
		...additional: counts for real/false paths if using the REWIRED link test

	Returns:
		None
	'''

	if depth == 0:
		return

	if source not in net:
		return

	for (interaction, target) in net[source]:

		# if we arrived here through a bad link, any continued path is counted as false
		pathStatus_ThisTarget = falsePathStatus
		(i_type, post_t_type) = classifyInteraction(interaction)
		if isRewired(interaction):
			pathStatus_ThisTarget = True

		# don't follow component links
		if i_type == 0:
			continue

		# activating nodes keep the signal, inactivating nodes reverse the signal
		action_this_target = None
		if i_type == 1:
			action_this_target = action
		elif i_type == 2:
			action_this_target = -action

		# for transcriptional states: the expression activity is what we want to measure 
		this_state = None
		if target in gene_states:	
			this_state = gene_states[target]
		#if post_t_type == "t":
		# this depends on weather we monitor the activities of downstream genes, or just the transcription
		# leave commented out for the former
		#	if target not in transcriptional_signs:
		#		continue
		#	this_state = transcriptional_signs[target] 

		# we hit a target that has a matching action/signal from the original source
		if (target in gene_states) and (target in target_set) \
			and (action_this_target == this_state):

			for (s,i,t) in linker_nodes:
				discovered.add((s,i,t))
			discovered.add((source, interaction, target))
			linker_nodes = set()
			new_linkers = set()
			# and keep going

			# add this to our TP or FP score, depending on the path
			if pathStatus_ThisTarget == True:
				falsePaths.append(target)
			else:
				truePaths.append(target)

		# search the target, but with any previous linkers	
		else:
			new_linkers = set()
			new_linkers.add((source, interaction, target))
			new_linkers = new_linkers.union(linker_nodes)	

		# if we come from a transcriptionally activating link, this cuts the cycle. Gene must
		# be upregulated 
		if post_t_type == "t":
			continue

		# add this link and keep searching from the target
		searchDFS(target, action_this_target, discovered, new_linkers, target_set, net, gene_states, transcriptional_signs, depth-1, truePaths, falsePaths, pathStatus_ThisTarget)

def classifyState(up_signs, down_signs):
	'''
	Build a hash of putative effects of perturbations,
	and inferred transcription activity.

	>>> classifyState({'A':"+",'B':"+"}, {'B':"-",'C':"-"})
	({'A': 1, 'C': -1, 'B': 1}, {'C': -1, 'B': -1})
	'''

	c = {}
	t_states = {}
	# The order matters here: 
	for gene in down_signs:
		if down_signs[gene] == "+":
			c[gene] = 1
			t_states[gene] = 1
		else:
			c[gene] = -1
			t_states[gene] = -1

	# The order matters here: 
	for gene in up_signs:
		if up_signs[gene] == "+":
			c[gene] = 1
		else:
			c[gene] = -1

	return (c, t_states)
	
# build an index, source to targets fro the directed graph
def parseNet(network, gene_universe=None):
	"""
	Build a directed network from a .sif file. 
	
	Inputs:
		A network in .sif format, tab-separated (<source> <interaction> <target>)

	Returns
		A network in hash key format, i.e. convert two lines of a file:
			<source>	<interaction1>	<target1>
			<source>	<interaction2>	<target2>
		To:	
			{'source': set( (interaction, target1), (interaction, target2) )
	"""
	net = {}
	for line in open(network, 'r'):

		parts = line.rstrip().split("\t")
		source = parts[0]
		interaction = parts[1]
		target = parts[2]

		# restrict to this gene set if necessary
		if gene_universe and (source not in gene_universe or target not in gene_universe):
			continue

		if source not in net:
			net[source] = set()

		net[source].add((interaction, target))

	return net

def mapUGraphToNetwork(edge_list, network):
	"""
		Map undirected edges to the network to form a subnetwork
		in the hash-key directed network format
	
		Input:
			edge_list: edges in (s,t) format
			network: network in {source:set( (int, target), ... )	

		Returns:
			Subnetwork in the data structure format of network input
	"""

	subnetwork = {}
	
	for (s,t) in edge_list:
		# find this equivalent edge(s) in the directed network
		# edges: 
		if s in network:
			for (i, nt) in network[s]:
				if nt == t:
					if s not in subnetwork:
						subnetwork[s] = set()
					subnetwork[s].add((i,t))	

		if t in network:
			for (i, nt) in network[t]:
				if nt == s:
					if t not in subnetwork:
						subnetwork[t] = set()
					subnetwork[t].add((i,s))	
	
	return subnetwork	


def connectedSubnets(network, subnet_nodes):

	"""

	Input: 
		A network in hash[source] = set( (interaction, target), ... ) Form
		A set of nodes to use for edge selection

	Returns: 
		An edgelist set (source, target) 
		where both nodes are in the subset of interest

	>>> network = {}
	>>> network['S1'] = set()
	>>> network['S2'] = set()
	>>> network['T2'] = set()
	>>> network['T1'] = set()
	>>> network['T3'] = set()
	>>> network['S1'].add(('a>','T1'))
	>>> network['S2'].add(('a>','T2'))
	>>> network['T1'].add(('t|','T2'))
	>>> network['T2'].add(('a>','T1'))
	>>> network['T3'].add(('t>','G5'))
	>>> connectedSubnets(network, set(['S1','T1','T2','T3','G5']))
	set([('S1', 'T1'), ('T1', 'T2'), ('T2', 'T1')])
	"""
	edgelist = set()
	ugraph = set()

	for s in network:
		for (i,t) in network[s]:
			# ignore self-links
			if s == t:
				continue
			if s in subnet_nodes and t in subnet_nodes:
				edgelist.add((s,t))
				if (t,s) not in edgelist:
					ugraph.add((s,t))

	# use networkx to find the largest connected sub graph
	G = nx.Graph()
	G.add_edges_from(list(ugraph))
		
	# get all connected components, add edges between them
	validated_edges = set()
	for (s,t) in edgelist:
		# validate both nodes
		if s in G.nodes() and t in G.nodes():
			validated_edges.add((s,t))	

	return validated_edges	


def getNXgraph(network, directed=True):

	"""
		Convert a hash-style network object into a directed nx graph object
	"""	
	# use networkx to find the largest connected sub graph
	G = None
	if directed:
		G = nx.DiGraph()
	else:
		G = nx.Graph()

	for s in network:
		for (i,t) in network[s]:
			# ignore self-links
			if s == t:
				continue
			G.add_edge(s,t)
			G[s][t]['i'] = i

	return G

def connectedNodes(network, hot_nodes):
	"""
	Call connectedSubnets to restrict to connected nodes, and return just the nodes
	filtered in this step
	"""
	
	nodes = set()
	for (s, t) in connectedSubnets(network, hot_nodes):
		nodes.add(s)
		nodes.add(t)
	return nodes

def runPCST(up_heats, down_heats, linker_genes, network_file):
	"""
		Convert input to format used for PCST program.
		Requires BioNet R package to be installed
	"""
	
	# convert up/down heats to p-values	
	# find the maximum heat for any value
	# the BioNet package requires p-values for an input, so we have to 'fake' these
	# here, converting them from heats. 
	s_up = sorted([v for k, v in up_heats.iteritems()], reverse=True)
	s_down = sorted([v for k, v in down_heats.iteritems()], reverse=True)

	if len(up_heats) > 0:	
		max_heat = s_up[0]
		min_heat = s_up[-1]
	
		if len(s_down) > 0:
			if s_down[0] > max_heat:
				max_heat = s_down[0]
				min_heat = s_up[-1]
			if s_down[-1] > min_heat:
				min_heat = s_down[-1]
	else:
		max_heat = 1
		min_heat = 1

	# take the sqrt of the fold difference over the min
	normalized_max = math.sqrt(max_heat/min_heat)
	scores = {}
	# the order is important here: there may be overlap between the source, target
	# and linker sets. The linkers are the highest priority, over the source/target.
	for node in down_heats:
		heat = down_heats[node]
		normalized_heat = math.sqrt(heat/min_heat)
		pval = math.exp( normalized_heat*math.log(float("1e-10"))/normalized_max )
		scores[node] = str(pval)
	for node in up_heats:
		heat = up_heats[node]
		normalized_heat = math.sqrt(heat/min_heat)
		pval = math.exp( normalized_heat*math.log(float("1e-10"))/normalized_max )
		scores[node] = str(pval)
	for node in linker_genes:
		scores[node] = "1e-10"	

	pid = str(os.geteuid())

	tmp_act = open("/tmp/tmp_act_"+pid+".tab",'w')
	for node in scores:
		tmp_act.write(node+"\t"+scores[node]+"\n")
	tmp_act.close()	

	# PCST is implemented in the BioNet package, and requires R to run. Python will call this script and collect the output
	os.system(sys.path[0]+"/span.R --activities /tmp/tmp_act_"+pid+".tab --network "+network_file+" > /tmp/pcst_"+pid+".tab 2>/dev/null")

	pcst_network = []
	pcst_line = re.compile("\[\d+\]\s+(\S+)\s+\-\-\s+(\S+)\s+")
	pcst = open("/tmp/pcst_"+pid+".tab",'r')	
	for line in pcst:
		m = pcst_line.match(line)	
		if m:
			pcst_network.append((m.group(1),m.group(2)))	
	pcst.close()

	return pcst_network	


def writeNetwork(net, out_file):

	out = open(out_file, 'w')
	for source in net:
		for (int, target) in net[source]:
			out.write("\t".join([source, int, target])+"\n")

	out.close()

def writeEL(el, out_file):

	out = open(out_file, 'w')
	for (source, int, target) in el:
		out.write("\t".join([source, int, target])+"\n")

	out.close()

def randomSubnet(network, num_sources):
	"""
	Take a random sample of nodes, of the specified size
	from the supplied network
	"""
	sub = {}
	for source in random.sample(network, num_sources):
		sub[source] = network[source]
			
	return sub

def writeNAfile(file_name, hash_values, attr_name):
	"""
	Write out a node-attribute file. Include the header 
	attr_name, and use the supplied hash values. 
	"""
	fh = None
	try:
		fh = open(file_name, 'w')	
	except:
		raise Exception("Error: couldn't open output NA file for writing:"+file_name)

	fh.write(attr_name+"\n")
	for key in hash_values:
		# check data type: hash values should be numbers for .NA file
		try:
			float(hash_values[key])
		except:
			raise Exception("Error: bad input value")
			
		fh.write(key+" = "+str(hash_values[key])+"\n")

	fh.close()

def writeHEATS(file_name, hash_values):
	"""
	Write out a node-attribute file. Include the header 
	attr_name, and use the supplied hash values. 
	"""
	fh = None
	try:
		fh = open(file_name, 'w')	
	except:
		raise Exception("Error: couldn't open output NA file for writing:"+file_name)

	for key in hash_values:
		# check data type: hash values should be numbers for .NA file
		try:
			float(hash_values[key])
		except:
			raise Exception("Error: bad input value")
			
		fh.write(key+"\t"+str(hash_values[key])+"\n")

	fh.close()

def sampleHeats(heats):

	ss = int(len(heats)*0.8)
	keys = random.sample(heats, ss)
	subset = {}
	for k in keys:
		subset[k] = heats[k] 

	return subset

def getNetworkNodes(network):
	"""
	Take a network in hash-key format and return a set containing the
	nodes in it. 
	"""
	nodes = set()
	for s in network:
		nodes.add(s)
		for (i, t) in network[s]:
			nodes.add(t)
	return nodes

def parseMatrix(file, restrict_samples=None, binary_threshold=0.0, transpose=False):
	''' 
		Sample IDS should be the header line. Gene ids are the row names
		
		Input:
			binary_threshold: 'include data values only if they fall above this range (abs val)
			tf_parents: 

		Options:
			transpose: index by rows, then columns, instead of the default column/row spec
			
	'''


	# indexed by sample then by gene	
	data = {}
	 
	first = True
	sampleIDS = None
	for line in open(file, 'r'):
		parts = line.rstrip().split("\t")
		row_id = parts[0]
		vals = parts[1:]
		if first:
			first = False
			column_ids = vals
			continue

		for i in range(0,len(vals)):
			val = None
			try:
				val = float(vals[i])
			except:
				continue
			column_id = column_ids[i]		

			if restrict_samples and column_id not in restrict_samples:
				continue
			if abs(val) < binary_threshold:
				continue	

			###
			### Get the gene expression, indexed by samples
			###
			if not transpose:
				if column_id not in data:
					data[column_id] = {}
				data[column_id][row_id] = val
			else:
				if row_id not in data:
					data[row_id] = {}
				data[row_id][column_id] = val

	return data

def getTFparents(network):
	'''
		Take a network object and index the upstream TFs for each gene
		and the type of interaction for each
		i.e. parents[gene] = (set(tf1, tf2....), {tf1:'a',tf2:'i'}}
	'''

	parents = {}
	children = {}
	for source in network:
		for (int, target) in network[source]:

			a_type, edge_type = classifyInteraction(int)
			act = None

			# only transcriptional
			if edge_type != "t":
				continue

			# only activating or inactivating
			if a_type == 1:
				act = "a"
			elif a_type == 0:
				act = "i"
			else:
				continue
	
			if target not in parents:
				parents[target] = (set(), {})
			
			parents[target][0].add(source)
			parents[target][1][source] = act

			if source not in children:
				children[source] = set()

			children[source].add(target)
	
	return (parents, children)	

def normalizeHeats(data, total=1000):
	"""

	"""
	FACTOR = total
	normalized = {}
	signs = {}
	sum = 0.0
	for (event, val) in data.items():
		sum += abs(val)

	for (event, val) in data.items():
		sign = "+"
		if val < 0:
			sign = "-"
		normalized[event] = FACTOR*abs(val) / sum
		signs[event] = sign

	return (normalized, signs)
	

def getActivityScores(expr_data, tf_genes, tf_parents, binary_threshold=0): 
	'''
		Takes expresion data and collapsed network information describing
		the transcriptional regulators of each gene, and combines it 
		to form an 'activity score' for each transcriptionally active gene.
		
		Input:
			expr_data: expression data indexed by sample, then gene
			binary_threshold: threshold to consider expression data (typically normal-subtracted values or
			z-scores). Defaults to 0 (i.e. no threshold)
			tf_genes: set of candidate TF regulators
			tf_parents: indexed dictionary that returns the parents of each gene	
	'''
	# the number of counts per gene, per sample 
	counts = {}
	# store the mean scores of each gene, for each sample
	activities = {}

	for sample in expr_data:
		activities[sample] = defaultdict(float)
		counts[sample] = defaultdict(int)
		for gene in expr_data[sample]:	

			val = expr_data[sample][gene]

			if abs(val) >= binary_threshold:

				if gene not in tf_parents:
					continue

				# check, is this downstream of a TF of interest? 
				# if so, add the TF, not the gene
				parents, activation_type = tf_parents[gene]
				for parent in tf_genes.intersection(parents):
				
					act = activation_type[parent]	
					tf_act = None
					# is this TF active? 
					if act == 'a':
						tf_act = val
					elif act == 'i':	
						tf_act = -1*val

					# add the activity, and the count
					activities[sample][parent] += tf_act
					counts[sample][parent] += 1

	# convert sums to means
	for sample in activities:
		for gene in activities[sample]:
			activities[sample][gene] = activities[sample][gene]/float(counts[sample][gene])

	return activities

def Mean(scores):
	'''
	Input: an array of scores

	Returns: the geometric mean of these scores
	'''

	epsilon = 0.00001
	sum = 0.0
	for score in scores:
		sum += score
	return sum/float(len(scores))

def weightedMean(scoresA, scoresB, w_A):
	'''
	Input: 2 hashes of scores across a set of genes
		- a weight/fraction for the first input

	Returns: the geometric mean of these scores
	'''

	w_B = 1-w_A	

	combined = {}
	for key in scoresA:
		mean = None
		if key not in scoresB:
			continue
	
		# compute the weighted geometric mean	
		combined[key] = float(scoresA[key])*w_A + float(scoresB[key])*w_B

	return combined

def mean(scoresA, scoresB, bias):
	'''
	Input: 2 hashes of scores across a set of genes

	Returns: the mean of these scores
	'''

	A_bias = bias
	B_bias = 1-bias	
	combined = {}
	for key in scoresA:
		mean = None
		if key not in scoresB:
			continue
		
		combined[key] = scoresA[key]*A_bias + scoresB[key]*B_bias

	return combined


def correct_pvalues_for_multiple_testing(pvalues, correction_type = "Benjamini-Hochberg"):				
	"""																								   
	Stolen from stackoverflow...

	consistent with R - print correct_pvalues_for_multiple_testing([0.0, 0.01, 0.029, 0.03, 0.031, 0.05, 0.069, 0.07, 0.071, 0.09, 0.1]) 
	"""
	from numpy import array, empty																		
	pvalues = array(pvalues) 
	n = float(pvalues.shape[0])																		   
	new_pvalues = empty(n)
	if correction_type == "Bonferroni":																   
		new_pvalues = n * pvalues
	elif correction_type == "Bonferroni-Holm":															
		values = [ (pvalue, i) for i, pvalue in enumerate(pvalues) ]									  
		values.sort()
		for rank, vals in enumerate(values):															  
			pvalue, i = vals
			new_pvalues[i] = (n-rank) * pvalue															
	elif correction_type == "Benjamini-Hochberg":														 
		values = [ (pvalue, i) for i, pvalue in enumerate(pvalues) ]									  
		values.sort()
		values.reverse()																				  
		new_values = []
		for i, vals in enumerate(values):																 
			rank = n - i
			pvalue, index = vals																		  
			new_values.append((n/rank) * pvalue)														  
		for i in xrange(0, int(n)-1):  
			if new_values[i] < new_values[i+1]:														   
				new_values[i+1] = new_values[i]														   
		for i, vals in enumerate(values):
			pvalue, index = vals
			new_pvalues[index] = new_values[i]																												  
	return new_pvalues

# SURF2017
# File: clustering.py
# Created: 7/10/17
# Author: Stephanie Ding
# Description:
# Perform various sorts of clustering processes. This file is mostly used for testing, a lot of the
# functional logic for dealing with .pcaps has been moved to PcapTools, and the clustering logic
# has been moved to the Detector.

from __future__ import division
import FlowParser as fp
import constants
from Detector import Model
import subprocess
import os
import errno
import re
import glob
import numpy as np
from datetime import date, datetime, timedelta
from sklearn.manifold import TSNE
from sklearn.cluster import KMeans, MiniBatchKMeans, DBSCAN
from sklearn import metrics
from sklearn import decomposition
from sklearn.externals import joblib
from sklearn.cluster import AgglomerativeClustering
import hdbscan
from sklearn.preprocessing import StandardScaler
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib import pyplot
from mpl_toolkits.mplot3d import Axes3D

'''
Splits a .pcap file into time windows of <window_size> seconds with <overlap> seconds overlapping between windows
Files are output to a folder with the name of the original pcap and the split files are named <1...n>.pcap
The folder name is returned for further actions (e.g. generating all netflows in the folder)
'''
def generate_windowed_pcaps(filepath, window_size, overlap):
    print("Opening " + filepath + "...")

    # Get time of first and last packet using editcaps
    output = subprocess.check_output(['capinfos', '-u', '-a', '-e', filepath])
    r_first = re.compile("First packet time:\s*(.*)$", re.MULTILINE)
    r_last = re.compile("Last packet time:\s*(.*)$", re.MULTILINE)

    # Parse times into datetime objects
    dt_first = datetime.strptime(r_first.search(output).groups(1)[0], "%Y-%m-%d %H:%M:%S.%f")
    dt_last = datetime.strptime(r_last.search(output).groups(1)[0], "%Y-%m-%d %H:%M:%S.%f") + timedelta(seconds=1)

    # Get basepath of pcap file and create new output folder for the split pcaps
    dirname, basename = os.path.split(filepath)
    filename, ext = os.path.splitext(basename)
    output_folder = os.path.join(dirname, '_'.join([re.sub('[^0-9a-zA-Z]+', '', filename), str(window_size), str(overlap)]))

    try:
        os.makedirs(output_folder)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    # Generator for datetime ranges
    def daterange(start, end, delta):
        curr = start
        while curr < end:
            yield curr
            curr += delta

    # For each interval, filter the packets in that time
    for i, d in enumerate(daterange(dt_first, dt_last, timedelta(seconds=overlap)), 1):
        start_time = d.strftime("%Y-%m-%d %H:%M:%S")
        end_time = (d + timedelta(seconds=window_size)).strftime("%Y-%m-%d %H:%M:%S")
        #print(start_time, end_time)
        new_filename = os.path.join(output_folder, str(i)) + ext
        args = ['editcap', '-A', start_time, '-B', end_time, '-F', 'pcap', filepath, new_filename]
        cmd = subprocess.list2cmdline(args)
        print(cmd)
        subprocess.call(args)

    return output_folder

'''
Generates all Argus bidirectional netflows for all the pcaps in a specified folder
'''
def generate_argus_binetflows(folder_name):
    os.chdir(folder_name)
    for file in glob.glob("*.pcap"):
        filename, ext = os.path.splitext(file)
        argusfile = filename + '.argus'
        args = ['argus', '-r', file, '-w', argusfile, '-ARJZ']
        subprocess.call(args)

        binetflow_file = filename + '.binetflow'
        print(binetflow_file)
        outfile = open(binetflow_file, 'w')
        args = ['ra', '-n', '-u', '-r', argusfile, '-s', 'srcid', 'stime', 'ltime', 'flgs', 'seq', 'smac', 'dmac',
                'soui', 'doui', 'saddr', 'daddr', 'proto', 'sport', 'dport', 'stos', 'dtos', 'sdsb', 'ddsb', 'sco',
                'dco', 'sttl', 'dttl', 'sipid', 'dipid', 'smpls', 'dmpls', 'spkts', 'dpkts', 'sbytes', 'dbytes',
                'sappbytes', 'dappbytes', 'sload', 'dload', 'sloss', 'dloss', 'sgap', 'dgap', 'dir', 'sintpkt',
                'dintpkt', 'sintdist', 'dintdist', 'sintpktact', 'dintpktact', 'sintdistact', 'dintdistact',
                'sintpktidl', 'dintpktidl', 'sintdistidl', 'dintdistidl', 'sjit', 'djit', 'sjitact', 'djitact',
                'sjitidle', 'djitidle', 'state', 'suser', 'duser', 'swin', 'dwin', 'svlan', 'dvlan', 'svid', 'dvid',
                'svpri', 'dvpri', 'srng', 'erng', 'stcpb', 'dtcpb', 'tcprtt', 'synack', 'ackdat', 'tcpopt', 'inode',
                'offset', 'spktsz', 'dpktsz', 'smaxsz', 'dmaxsz', 'sminsz', 'dminsz', 'dur', 'rate', 'srate', 'drate',
                'trans', 'runtime', 'mean', 'stddev', 'sum', 'min', 'max', 'pkts', 'bytes', 'appbytes', 'load', 'loss',
                'ploss', 'sploss', 'dploss', 'abr', '-c', ',']
        #cmd = subprocess.list2cmdline(args)
        subprocess.call(args, stdout=outfile)
        outfile.close()

# Outputs TSNE for all binetflow files in a folder
def batch_tsne(folder_name, infection_start, labelled):
    os.chdir(folder_name)

    try:
        os.makedirs('tsne')
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

    for file in glob.glob("*.binetflow"):
        filename, ext = os.path.splitext(file)
        infected = False if int(filename) < infection_start else True
        output_file = os.path.join(folder_name, 'tsne', filename) + '.png'
        generate_tsne(5000, infected, labelled, file, output_file)

def generate_tsne(num_flows, infected, labelled, unlabelled, output_file):
    #dataset_no = int(input("Enter the number for the dataset: "))
    #labelled = raw_input("Enter the filename for the labelled Argus binetflows: ")
    #unlabelled = raw_input("Enter the filename for the unlabelled Argus binetflows: ")

    flows, xs, ys = fp.parse_argus(labelled, unlabelled)

    tsne = TSNE(n_components=2, verbose=1, perplexity=40, n_iter=300)
    tsne_results = tsne.fit_transform(xs[:num_flows])

    x1 = []
    y1 = []

    x2 = []
    y2 = []

    if not infected:
        for i in range(num_flows):
            x1.append(tsne_results[i][0])
            y1.append(tsne_results[i][1])
    else:
        for i in range(num_flows):
            if ys[i] == 0:
                x1.append(tsne_results[i][0])
                y1.append(tsne_results[i][1])
            else:
                x2.append(tsne_results[i][0])
                y2.append(tsne_results[i][1])

    # Create plot
    plt.ioff()
    fig = plt.figure(figsize=(8, 8), dpi=100, facecolor='w', edgecolor='k')
    ax = fig.add_subplot(1, 1, 1)
    ax.set_autoscalex_on(False)
    ax.set_autoscaley_on(False)
    ax.set_xlim([-30, 30])
    ax.set_ylim([-30, 30])

    ax.scatter(x1, y1, alpha=0.8, c="blue", edgecolors='none', s=30, label="normal")
    ax.scatter(x2, y2, alpha=0.8, c="red", edgecolors='none', s=30, label="botnet")

    #plt.title("CTU-13 Dataset " + str(dataset_no) + " t-SNE")
    plt.legend(loc=2)
    fig.savefig(output_file, bbox_inches='tight')
    plt.close(fig)
    #plt.show()

def get_cluster_statistics(clusters):
    print("Number of clusters: " + str(len(clusters)))
    # for i in clusters:
    #     print("\n"+ str(i))
    #     print(", ".join(clusters[i]))

def dbscan():
    # some ugly hard coded values, ignore this
    nb_file = "/media/SURF2017/CTU-13-Dataset/9/capture20110817pcaptruncated_300_150/7.binetflow"
    b_file = "/media/SURF2017/CTU-13-Dataset/9/capture20110817pcaptruncated_300_150/86.binetflow"
    labels_file = "/media/SURF2017/CTU-13-Dataset/9/capture20110817.binetflow"

    features_list = raw_input("Enter space-separated list of features (or press enter to use default set of 40): ")

    try:
        if features_list != '':
            features_list = features_list.split()
        else:
            features_list = fp.ARGUS_FIELDS
    except Exception, e:
        features_list = fp.ARGUS_FIELDS

    print("Using features list: " + str(features_list))

    print("\nDBSCAN on non-botnet infected interval: ")

    nb_flows, nb_xs, nb_ys = fp.parse_ctu(nb_file, labels_file, features_list)
    nb_xs = StandardScaler().fit_transform(nb_xs)

    # print("Running PCA...")
    # pca = decomposition.PCA()
    # nb_xs_reduced = pca.fit_transform(nb_xs)
    # print("Shape after PCA: " + str(nb_xs_reduced.shape))


    nb_db = DBSCAN(eps=0.3, min_samples=10).fit(nb_xs)
    nb_labels = nb_db.labels_

    nb_clusters = {}
    for flow, label in zip(nb_flows, nb_labels):
        src, dst = fp.get_src_dst(flow)
        #if src.startswith("147.32"):
        if label not in nb_clusters:
            nb_clusters[label] = {src}
        else:
            nb_clusters[label].add(src)

    get_cluster_statistics(nb_clusters)

    print("\nDBSCAN on botnet infected interval: ")

    b_flows, b_xs, b_ys = fp.parse_ctu(b_file, labels_file, features_list)
    b_xs = StandardScaler().fit_transform(b_xs)

    # print("Running PCA...")
    # pca = decomposition.PCA()
    # b_xs_reduced = pca.fit_transform(b_xs)
    # print("Shape after PCA: " + str(b_xs_reduced.shape))

    b_db = DBSCAN(eps=0.3, min_samples=10).fit(b_xs)
    b_labels = b_db.labels_

    b_clusters = {}
    for flow, label in zip(b_flows, b_labels):
        src, dst = fp.get_src_dst(flow)
        #if src.startswith("147.32"):
        if label not in b_clusters:
            b_clusters[label] = {src}
        else:
            b_clusters[label].add(src)

    get_cluster_statistics(b_clusters)

'''
Clustering logic copied over from detector, without GUI
'''
def visualize_clustering_tsne(filename, model_filename, savepath, dataset_no, infection_range):
    internal_hosts_prefix = "147.32"
    infected_IPs = eval("constants.DATASET_" + str(dataset_no) + "_INFECTED_HOSTS")
    window = int(filename.split("/")[-1].strip(".binetflow"))

    print("Loading model: " + model_filename)
    model = Model(model_filename, fp.ARGUS_FIELDS, internal_hosts_prefix)
    print("Parsing file: " + filename)
    flows, xs = fp.parse_binetflow(filename)

    print("Parsed " + str(len(flows)) + " flows, predicting...")
    model.predict(flows, xs)

    botnet_flows = model.get_botnet_flows()

    # Do clustering on suspected botnet flows
    botnet_hosts = {}

    for flow, x in botnet_flows:
        x = list(x)
        src, dst = fp.get_src_dst(flow)

        if src.startswith(internal_hosts_prefix):
            if src not in botnet_hosts:
                botnet_hosts[src] = {}
                botnet_hosts[src]['count'] = 1
                botnet_hosts[src]['srcpkts'] = x[2]
                botnet_hosts[src]['dstpkts'] = x[3]
                botnet_hosts[src]['srcbytes'] = x[4]
                botnet_hosts[src]['dstbytes'] = x[5]
                botnet_hosts[src]['unique_ports'] = {flow[3]}
                botnet_hosts[src]['unique_dsts'] = {dst}
            else:
                botnet_hosts[src]['count'] += 1
                botnet_hosts[src]['srcpkts'] += x[2]
                botnet_hosts[src]['dstpkts'] += x[3]
                botnet_hosts[src]['srcbytes'] += x[4]
                botnet_hosts[src]['dstbytes'] += x[5]
                botnet_hosts[src]['unique_ports'].add(flow[3])
                botnet_hosts[src]['unique_dsts'].add(dst)

        if dst.startswith(internal_hosts_prefix):
            if dst not in botnet_hosts:
                botnet_hosts[dst] = {}
                botnet_hosts[dst]['count'] = 1
                botnet_hosts[dst]['srcpkts'] = x[3]
                botnet_hosts[dst]['dstpkts'] = x[2]
                botnet_hosts[dst]['srcbytes'] = x[5]
                botnet_hosts[dst]['dstbytes'] = x[4]
                botnet_hosts[dst]['unique_ports'] = {flow[1]}
                botnet_hosts[dst]['unique_dsts'] = {src}
            else:
                botnet_hosts[dst]['count'] += 1
                botnet_hosts[dst]['srcpkts'] += x[3]
                botnet_hosts[dst]['dstpkts'] += x[2]
                botnet_hosts[dst]['srcbytes'] += x[5]
                botnet_hosts[dst]['dstbytes'] += x[4]
                botnet_hosts[dst]['unique_ports'].add(flow[1])
                botnet_hosts[dst]['unique_dsts'].add(src)

    ips = []
    new_xs = []

    for host in botnet_hosts:
        ips.append(host)
        curr = botnet_hosts[host]
        new_xs.append(
            [curr['count'], curr['srcpkts'], curr['dstpkts'], curr['srcbytes'], curr['dstbytes'],
             len(curr['unique_ports']) / 65535, len(curr['unique_dsts'])])

    scaled_xs = StandardScaler().fit_transform(new_xs)

    # Tsne
    print("Doing TSNE...")
    # tsne = TSNE(n_components=2, verbose=1, perplexity=30, n_iter=1000, learning_rate=10) # DS 9
    #tsne = TSNE(n_components=2, verbose=1, perplexity=5, n_iter=1000, learning_rate=3) # DS6
    tsne = TSNE(n_components=2, verbose=1, perplexity=5, n_iter=1000, learning_rate=10) # DS 10
    tsne_results = tsne.fit_transform(scaled_xs)

    print("Doing clustering...")
    # clusterer = hdbscan.RobustSingleLinkage(gamma=1)
    # clusterer.fit_predict(scaled_xs)
    #
    #
    # hierarchy = clusterer.cluster_hierarchy_._linkage
    # hierarchy.plot()
    # plt.show()
    #
    # cluster_labels = hierarchy.get_clusters(8.2, min_cluster_size=1)
    # for i, j in zip(cluster_labels, ips):
    #    print(i, j)
    # clusterer = hdbscan.HDBSCAN(min_cluster_size=1, allow_single_cluster=True).fit(scaled_xs)

    ac = AgglomerativeClustering(affinity="euclidean", linkage="ward")
    #ac = KMeans(n_clusters=2)
    ac.fit(scaled_xs)
    labels = ac.labels_

    #clusters = {}
    cluster0 = []
    cluster1 = []

    for host, label, t in zip(ips, labels, tsne_results):
        if label == 0:
            cluster0.append((host, t))
        elif label == 1:
            cluster1.append((host, t))
        else:
            raise

    # define 0 as the majority/normal cluster and 1 as the anomalous cluster
    if len(cluster1) > len(cluster0):
        cluster0, cluster1 = cluster1, cluster0

    print("Processing clustering output...")

    tp_x = []
    tp_y = []

    fp_x = []
    fp_y = []

    tn_x = []
    tn_y = []

    fn_x = []
    fn_y = []

    for host, t in cluster0:
        if (window >= infection_range[0] and window <= infection_range[1]) and host in infected_IPs:
            fn_x.append(t[0])
            fn_y.append(t[1])
        else:
            tn_x.append(t[0])
            tn_y.append(t[1])

    for host, t in cluster1:
        if (window >= infection_range[0] and window <= infection_range[1]) and host in infected_IPs:
            tp_x.append(t[0])
            tp_y.append(t[1])
        else:
            fp_x.append(t[0])
            fp_y.append(t[1])

    # normal in blue, botnet in red
    fig, ax = plt.subplots()
    ax.xaxis.set_ticklabels([])
    ax.yaxis.set_ticklabels([])
    ax.set_autoscalex_on(True)
    ax.set_autoscaley_on(True)
    # ax.set_xlim([-3, 3])
    # ax.set_ylim([-3, 3])

    ax.scatter(tn_x, tn_y, color='blue', s=8, label='true negative IPs')
    ax.scatter(fn_x, fn_y, color='blue', marker='x', label='false negative IPs')
    ax.scatter(fp_x, fp_y, color='red', marker='x', label='false positive IPs')
    ax.scatter(tp_x, tp_y, color='red', s=8, label='true positive IPs')

    fig.suptitle("CTU-13 Dataset " + str(dataset_no) + " t-SNE, window=" + str(window))
    plt.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc=3,
           ncol=4, mode="expand", borderaxespad=0., prop={'size':6})
    fig.savefig(savepath, bbox_inches='tight')
    #plt.show()
    plt.close(fig)

'''
Clustering logic copied over from detector, without GUI
'''
def visualize_clustering_tsne(filename, model_filename, savepath, dataset_no, infection_range):
    internal_hosts_prefix = "147.32"
    infected_IPs = eval("constants.DATASET_" + str(dataset_no) + "_INFECTED_HOSTS")
    window = int(filename.split("/")[-1].strip(".binetflow"))

    print("Loading model: " + model_filename)
    model = Model(model_filename, fp.ARGUS_FIELDS, internal_hosts_prefix)
    print("Parsing file: " + filename)
    flows, xs = fp.parse_binetflow(filename)

    print("Parsed " + str(len(flows)) + " flows, predicting...")
    model.predict(flows, xs)

    botnet_flows = model.get_botnet_flows()

    # Do clustering on suspected botnet flows
    botnet_hosts = {}

    for flow, x in botnet_flows:
        x = list(x)
        src, dst = fp.get_src_dst(flow)

        if src.startswith(internal_hosts_prefix):
            if src not in botnet_hosts:
                botnet_hosts[src] = {}
                botnet_hosts[src]['count'] = 1
                botnet_hosts[src]['srcpkts'] = x[2]
                botnet_hosts[src]['dstpkts'] = x[3]
                botnet_hosts[src]['srcbytes'] = x[4]
                botnet_hosts[src]['dstbytes'] = x[5]
                botnet_hosts[src]['unique_ports'] = {flow[3]}
                botnet_hosts[src]['unique_dsts'] = {dst}
            else:
                botnet_hosts[src]['count'] += 1
                botnet_hosts[src]['srcpkts'] += x[2]
                botnet_hosts[src]['dstpkts'] += x[3]
                botnet_hosts[src]['srcbytes'] += x[4]
                botnet_hosts[src]['dstbytes'] += x[5]
                botnet_hosts[src]['unique_ports'].add(flow[3])
                botnet_hosts[src]['unique_dsts'].add(dst)

        if dst.startswith(internal_hosts_prefix):
            if dst not in botnet_hosts:
                botnet_hosts[dst] = {}
                botnet_hosts[dst]['count'] = 1
                botnet_hosts[dst]['srcpkts'] = x[3]
                botnet_hosts[dst]['dstpkts'] = x[2]
                botnet_hosts[dst]['srcbytes'] = x[5]
                botnet_hosts[dst]['dstbytes'] = x[4]
                botnet_hosts[dst]['unique_ports'] = {flow[1]}
                botnet_hosts[dst]['unique_dsts'] = {src}
            else:
                botnet_hosts[dst]['count'] += 1
                botnet_hosts[dst]['srcpkts'] += x[3]
                botnet_hosts[dst]['dstpkts'] += x[2]
                botnet_hosts[dst]['srcbytes'] += x[5]
                botnet_hosts[dst]['dstbytes'] += x[4]
                botnet_hosts[dst]['unique_ports'].add(flow[1])
                botnet_hosts[dst]['unique_dsts'].add(src)

    ips = []
    new_xs = []

    for host in botnet_hosts:
        ips.append(host)
        curr = botnet_hosts[host]
        new_xs.append(
            [curr['count'], curr['srcpkts'], curr['dstpkts'], curr['srcbytes'], curr['dstbytes'],
             len(curr['unique_ports']) / 65535, len(curr['unique_dsts'])])

    scaled_xs = StandardScaler().fit_transform(new_xs)

    # Tsne
    print("Doing TSNE...")
    # tsne = TSNE(n_components=2, verbose=1, perplexity=30, n_iter=1000, learning_rate=10) # DS 9
    #tsne = TSNE(n_components=2, verbose=1, perplexity=5, n_iter=1000, learning_rate=3) # DS6
    #tsne = TSNE(n_components=2, verbose=1, perplexity=5, n_iter=1000, learning_rate=10) # DS 10

    tsne = TSNE(n_components=3, verbose=1, perplexity=30, n_iter=1000, learning_rate=10)  # DS 9
    tsne_results = tsne.fit_transform(scaled_xs)

    print("Doing clustering...")
    # clusterer = hdbscan.RobustSingleLinkage(gamma=1)
    # clusterer.fit_predict(scaled_xs)
    #
    #
    # hierarchy = clusterer.cluster_hierarchy_._linkage
    # hierarchy.plot()
    # plt.show()
    #
    # cluster_labels = hierarchy.get_clusters(8.2, min_cluster_size=1)
    # for i, j in zip(cluster_labels, ips):
    #    print(i, j)
    # clusterer = hdbscan.HDBSCAN(min_cluster_size=1, allow_single_cluster=True).fit(scaled_xs)

    ac = AgglomerativeClustering(affinity="euclidean", linkage="ward")
    #ac = KMeans(n_clusters=2)
    ac.fit(scaled_xs)
    labels = ac.labels_

    #clusters = {}
    cluster0 = []
    cluster1 = []

    for host, label, t in zip(ips, labels, tsne_results):
        if label == 0:
            cluster0.append((host, t))
        elif label == 1:
            cluster1.append((host, t))
        else:
            raise

    # define 0 as the majority/normal cluster and 1 as the anomalous cluster
    if len(cluster1) > len(cluster0):
        cluster0, cluster1 = cluster1, cluster0

    print("Processing clustering output...")

    tp_x = []
    tp_y = []
    tp_z = []

    fp_x = []
    fp_y = []
    fp_z = []

    tn_x = []
    tn_y = []
    tn_z = []

    fn_x = []
    fn_y = []
    fn_z = []

    for host, t in cluster0:
        if (window >= infection_range[0] and window <= infection_range[1]) and host in infected_IPs:
            fn_x.append(t[0])
            fn_y.append(t[1])
            fn_z.append(t[2])
        else:
            tn_x.append(t[0])
            tn_y.append(t[1])
            tn_z.append(t[2])

    for host, t in cluster1:
        if (window >= infection_range[0] and window <= infection_range[1]) and host in infected_IPs:
            tp_x.append(t[0])
            tp_y.append(t[1])
            tp_z.append(t[2])
        else:
            fp_x.append(t[0])
            fp_y.append(t[1])
            fp_z.append(t[2])

    # normal in blue, botnet in red
    #fig, ax = plt.subplots()

    fig = pyplot.figure()
    ax = Axes3D(fig)
    ax.xaxis.set_ticklabels([])
    ax.yaxis.set_ticklabels([])
    ax.zaxis.set_ticklabels([])
    ax.set_autoscalex_on(True)
    ax.set_autoscaley_on(True)
    ax.set_autoscalez_on(True)
    # ax.set_xlim([-3, 3])
    # ax.set_ylim([-3, 3])

    ax.scatter(tn_x, tn_y, tn_z, color='blue', s=8, label='true negative IPs')
    ax.scatter(fn_x, fn_y, fn_z, color='blue', marker='x', label='false negative IPs')
    ax.scatter(fp_x, fp_y, fp_z, color='red', marker='x', label='false positive IPs')
    ax.scatter(tp_x, tp_y, tp_z, color='red', s=8, label='true positive IPs')

    fig.suptitle("CTU-13 Dataset " + str(dataset_no) + " t-SNE, window=" + str(window))
    plt.legend(bbox_to_anchor=(0., 1.02, 1., .102), loc=3,
           ncol=4, mode="expand", borderaxespad=0., prop={'size':6})
    #fig.savefig(savepath, bbox_inches='tight')
    plt.show()
    #plt.close(fig)


'''
Evaluate a particular clustering method
'''
def evaluate_clustering_performance(clusterer, folder_name, model_filename, infected_ips, infection_range):
    total_ips = 0
    total_fp = 0
    total_fn = 0
    total_tp = 0
    total_tn = 0

    internal_hosts_prefix = "147.32"

    print("Loading model: " + model_filename)
    model = Model(model_filename, fp.ARGUS_FIELDS, internal_hosts_prefix)


    for window in range(1, infection_range[1]):
        filename = folder_name + str(window) + ".binetflow"
        print("Parsing file: " + filename)
        flows, xs = fp.parse_binetflow(filename)

        model.predict(flows, xs)
        botnet_flows = model.get_botnet_flows()

        # Do clustering on suspected botnet flows
        botnet_hosts = {}

        for flow, x in botnet_flows:
            x = list(x)
            src, dst = fp.get_src_dst(flow)

            if src.startswith(internal_hosts_prefix):
                if src not in botnet_hosts:
                    botnet_hosts[src] = {}
                    botnet_hosts[src]['count'] = 1
                    botnet_hosts[src]['srcpkts'] = x[2]
                    botnet_hosts[src]['dstpkts'] = x[3]
                    botnet_hosts[src]['srcbytes'] = x[4]
                    botnet_hosts[src]['dstbytes'] = x[5]
                    botnet_hosts[src]['unique_ports'] = {flow[3]}
                    botnet_hosts[src]['unique_dsts'] = {dst}
                else:
                    botnet_hosts[src]['count'] += 1
                    botnet_hosts[src]['srcpkts'] += x[2]
                    botnet_hosts[src]['dstpkts'] += x[3]
                    botnet_hosts[src]['srcbytes'] += x[4]
                    botnet_hosts[src]['dstbytes'] += x[5]
                    botnet_hosts[src]['unique_ports'].add(flow[3])
                    botnet_hosts[src]['unique_dsts'].add(dst)

            if dst.startswith(internal_hosts_prefix):
                if dst not in botnet_hosts:
                    botnet_hosts[dst] = {}
                    botnet_hosts[dst]['count'] = 1
                    botnet_hosts[dst]['srcpkts'] = x[3]
                    botnet_hosts[dst]['dstpkts'] = x[2]
                    botnet_hosts[dst]['srcbytes'] = x[5]
                    botnet_hosts[dst]['dstbytes'] = x[4]
                    botnet_hosts[dst]['unique_ports'] = {flow[1]}
                    botnet_hosts[dst]['unique_dsts'] = {src}
                else:
                    botnet_hosts[dst]['count'] += 1
                    botnet_hosts[dst]['srcpkts'] += x[3]
                    botnet_hosts[dst]['dstpkts'] += x[2]
                    botnet_hosts[dst]['srcbytes'] += x[5]
                    botnet_hosts[dst]['dstbytes'] += x[4]
                    botnet_hosts[dst]['unique_ports'].add(flow[1])
                    botnet_hosts[dst]['unique_dsts'].add(src)

        ips = []
        new_xs = []

        for host in botnet_hosts:
            ips.append(host)
            curr = botnet_hosts[host]
            new_xs.append(
                [curr['count'], curr['srcpkts'], curr['dstpkts'], curr['srcbytes'], curr['dstbytes'],
                 len(curr['unique_ports']) / 65535, len(curr['unique_dsts'])])

        try:
            scaled_xs = StandardScaler().fit_transform(new_xs)
            clusterer.fit(scaled_xs)
            labels = clusterer.labels_
        except Exception as e:
            continue

        # clusters = {}
        cluster0 = set()
        cluster1 = set()

        for host, label in zip(ips, labels):
            if label == 0:
                cluster0.add(host)
            elif label == 1:
                cluster1.add(host)
            else:
                raise

        # define 0 as the majority/normal cluster and 1 as the anomalous cluster
        if len(cluster1) > len(cluster0):
            cluster0, cluster1 = cluster1, cluster0

        for host in cluster0:
            total_ips += 1
            if (window >= infection_range[0] and window <= infection_range[1]) and host in infected_ips:
                total_fn += 1
            else:
                total_tn += 1

        for host in cluster1:
            total_ips += 1
            if (window >= infection_range[0] and window <= infection_range[1]) and host in infected_ips:
                total_tp += 1
            else:
                total_fp += 1

    print("total IPs: " + str(total_ips) + "\ttotal tp: " + str(total_tp) + "\ttotal fp: " + str(total_fp) + "\ttotal fn: " + str(total_fn) + "\ttotal tn: " + str(total_tn))

def main():
    DIR_PATH = "/media/SURF2017/SURF2017/datasets/9/capture20110817truncated_300_150/"
    MODEL_FILE = "/media/SURF2017/SURF2017/models/ctu9_40_300.pkl"
    FOLDER_NAME = "ag_ward_3D/"

    for i in range(86, 87):
        binetflow_file = DIR_PATH + str(i) + ".binetflow"
        save_path = DIR_PATH + FOLDER_NAME + str(i) + ".png"
        visualize_clustering_tsne(binetflow_file, MODEL_FILE, save_path, 9, (54, 123))

    #clusterer = AgglomerativeClustering(affinity='euclidean', linkage='ward')
    #clusterer = KMeans(n_clusters=2)
    #evaluate_clustering_performance(clusterer, DIR_PATH, MODEL_FILE, constants.DATASET_13_INFECTED_HOSTS, (2, 394))

    #pcap_file = raw_input("Enter the .pcap file: ")
    #labelled_file = raw_input("Enter the labelled file: ")
    #output_folder = generate_windowed_pcaps(pcap_file, 300, 150)
    #generate_argus_binetflows(output_folder)
    #batch_tsne('/media/SURF2017/CTU-13-Dataset/9/capture20110817pcaptruncated_300_150/', 56, '/media/SURF2017/CTU-13-Dataset/9/capture20110817.binetflow')
    #dbscan()


if __name__ == "__main__":
    main()

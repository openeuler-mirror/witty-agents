import asyncio

import numpy as np
import random
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from src.schemas.log import LogModel
from src.schemas.cluster import ClusterModel


class ClusterService:
    @staticmethod
    async def single_DBSCAN(
        eps: float,
        min_samples: int,
        clusters: list[ClusterModel]
    ) -> list[ClusterModel]:
        """
        单次DBSCAN聚类
        """
        if not clusters:
            return []
        
        centers = []
        for cluster in clusters:
            centers.append(cluster.cluster_center)
        centers_np = np.array(centers)
        scaler = StandardScaler()
        centers_scaled = scaler.fit_transform(centers_np)
        dbscan = DBSCAN(eps=eps, min_samples=min_samples)
        labels = dbscan.fit_predict(centers_scaled)
        new_clusters = []
        new_clusters_dict = {}
        for i, label in enumerate(labels):
            if label == -1:
                new_clusters.append(clusters[i])
                new_clusters[-1].is_outlier = True
                continue
            if label not in new_clusters_dict:
                new_clusters_dict[label] = clusters[i]
            else:
                new_clusters_dict[label].log_models.extend(
                    clusters[i].log_models)
        clusters_extend = new_clusters_dict.values()
        for cluster in clusters_extend:
            cluster.is_outlier = False
        new_clusters += clusters_extend
        for cluster in new_clusters:
            if cluster.log_models:
                cluster.cluster_center = np.mean(
                    [log_model.template_vector for log_model in cluster.log_models if log_model.template_vector is not None], axis=0).tolist()
        return new_clusters

    @staticmethod
    async def DBSCAN(
        log_models: list[LogModel],
        # 最大聚类次数
        max_iterations: int = 10,
        # 最小样本数
        min_samples: int = 20,
        # 每批次处理的聚类数量
        batch_size: int = 8192,
        # 距离
        eps: float = 0.5,
    ) -> list[ClusterModel]:
        """
        DBSCAN聚类服务
        层次化识别离群点，每次将要聚类的特征分为k条一个batch进行聚类，提取离群点，对于提取的离群点的数量小于阈值
        则将这些离群点加入到下一个batch中继续进行聚类，直到所有特征都被处理完毕
        这样做的目的是为了减少内存占用，防止一次性将所有特征进行聚类导致内存溢出
        但这样做的缺点是可能会导致离群点识别不够准确
        """
        if not log_models:
            return []
        
        clusters = []
        for log in log_models:
            cluster = ClusterModel(
                cluster_center=log.template_vector or [],
                log_models=[log]
            )
            clusters.append(cluster)
        iteration = 0
        while 1:
            if len(clusters) <= 5*batch_size or iteration >= max_iterations:
                # 最后一次聚类，并break
                clusters = await ClusterService.single_DBSCAN(eps, min_samples, clusters)
                break
            new_clusters = []
            random.shuffle(clusters)
            dbscan_tasks = []
            for i in range(0, len(clusters), batch_size):
                batch_clusters = clusters[i:i + batch_size]
                dbscan_tasks.append(ClusterService.single_DBSCAN(
                    eps, min_samples, batch_clusters))
            dbscan_results = await asyncio.gather(*dbscan_tasks)
            for dbscan_result in dbscan_results:
                new_clusters.extend(dbscan_result)
            clusters = new_clusters
            iteration += 1
        return clusters

    @staticmethod
    async def single_KMeans(
        n_clusters: int,
        n_init: int,
        random_state: int,
        clusters: list[ClusterModel]
    ) -> list[ClusterModel]:
        """
        单次KMeans聚类
        """
        if not clusters:
            return []
        
        n_clusters = min(n_clusters, len(clusters))
        if n_clusters == 0:
            return []
        
        vectors = [cluster.cluster_center for cluster in clusters]
        kmeans = KMeans(n_clusters=n_clusters, n_init=n_init,
                        random_state=random_state)
        labels = kmeans.fit_predict(vectors)
        new_clusters_dict = {}
        for i, label in enumerate(labels):
            if label not in new_clusters_dict:
                new_clusters_dict[label] = clusters[i]
            else:
                new_clusters_dict[label].log_models.extend(
                    clusters[i].log_models)
        centers = kmeans.cluster_centers_
        for label, cluster in new_clusters_dict.items():
            cluster.cluster_center = centers[label].tolist()
        return list(new_clusters_dict.values())

    @staticmethod
    async def KMeans(
        log_models: list[LogModel],
        # 每批次处理的聚类数量
        batch_size: int = 8192,
        # 最大聚类次数
        max_iterations: int = 10,
        # 聚类数量
        n_clusters: int = 10,
        # 迭代次数
        n_init: int = 10,
        # 随机种子
        random_state: int = 42,
    ) -> list[ClusterModel]:
        """
        KMeans聚类服务
        层次化聚类，每次将要聚类的特征分为k条一个batch进行聚类，最后将所有batch的聚类结果再进行一次聚类直到所有聚类结果合并为止
        这样做的目的是为了减少内存占用，防止一次性将所有特征进行聚类导致内存溢出
        但这样做的缺点是可能会导致聚类结果不够准确
        """
        if not log_models:
            return []
        
        clusters = []
        for log_model in log_models:
            cluster = ClusterModel(
                cluster_center=log_model.template_vector or [],
                log_models=[log_model]
            )
            clusters.append(cluster)
        n_clusters = min(n_clusters, len(clusters))
        if n_clusters == 0:
            return []
        iteration = 0
        while 1:
            if len(clusters) <= n_clusters*batch_size or iteration >= max_iterations:
                # 最后一次聚类，并break
                clusters = await ClusterService.single_KMeans(
                    n_clusters, n_init, random_state, clusters)
                break
            new_clusters = []
            random.shuffle(clusters)
            kmeans_tasks = []
            for i in range(0, len(clusters), batch_size):
                batch_clusters = clusters[i:i + batch_size]
                kmeans_tasks.append(ClusterService.single_KMeans(
                    n_clusters, n_init, random_state, batch_clusters))
            kmeans_results = await asyncio.gather(*kmeans_tasks)
            for kmeans_result in kmeans_results:
                new_clusters.extend(kmeans_result)
            clusters = new_clusters
            iteration += 1
        return clusters

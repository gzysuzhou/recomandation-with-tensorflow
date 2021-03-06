# -*- coding: UTF-8 -*-
import pandas as pd
import numpy as np
import tensorflow as tf
import time
import redis
import pickle
from prehandle import PreHandle
from pandas.core.frame import DataFrame
import sys
class Recommand(object):
    
    redis = None
    postKey = "postMap"
    recommandResultKey = "recommandResult"

    def __init__(self):
        Recommand.redis = redis.Redis(host='127.0.0.1', port=6379, db=0)

    def run(self, userID, skip, limit):
        self.cleanData()
        self.createMat()
        self.getTrainModel()
        return self.trainningModel(userID, skip, limit)

    '''
    第一步：收集和清洗数据
    '''
    def cleanData(self):
        ratings = Recommand.redis.hgetall(PreHandle.userPostScoreHashKey)
        userIDs = []
        postIDs = []
        scores = []
        for (userID, values) in ratings.items():
            for v in pickle.loads(values):
                userIDs.append(int(userID))
                postIDs.append(v["postID"])
                scores.append(v["score"])
        c = {"userID": userIDs, "postID": postIDs, "score": scores}
        ratings_df = DataFrame(c) #将字典转换成为数据框
        post_tags = Recommand.redis.hgetall(PreHandle.postTagHashKey)
        postIDs = []
        tags = []
        for (postID, value) in post_tags.items():
            postIDs.append(postID.decode())
            tags.append(value.decode())
        t = {"postID": postIDs, "tag": tags}
        posts_df = DataFrame(t)
        posts_df['postRow'] = posts_df.index
        self.posts_df = posts_df[['postRow','postID']]
        ratings_df = pd.merge(ratings_df, posts_df, on='postID')
        self.ratings_df = ratings_df[['userID','postRow','score']]
        
    def getPostsDf(self):
        post_tags = Recommand.redis.hgetall(PreHandle.postTagHashKey)
        postIDs = []
        tags = []
        for (postID, value) in post_tags.items():
            postIDs.append(postID.decode())
            tags.append(value.decode())
        t = {"postID": postIDs, "tag": tags}
        posts_df = DataFrame(t)
        posts_df['postRow'] = posts_df.index
        self.posts_df = posts_df[['postRow','postID']]
        return self.posts_df
    

    '''
    第二步：创建作品评分矩阵rating和评分纪录矩阵record
    '''
    def createMat(self):
        self.userNo = self.ratings_df['userID'].max() + 1
        self.postNo = self.ratings_df['postRow'].max() + 1
        rating = np.zeros((self.postNo, self.userNo))
        #创建一个值都是0的数据
        flag = 0
        ratings_df_length = np.shape(self.ratings_df)[0]
        #查看矩阵ratings_df的第一维度是多少
        for index, row in self.ratings_df.iterrows():
            #interrows（），对表格ratings_df进行遍历
            rating[int(row['postRow']), int(row['userID'])] = row['score']
            #将ratings_df表里的'postRow'和'userId'列，填上row的‘评分’
            flag += 1
        record = rating > 0
        self.rating = rating
        self.record = np.array(record, dtype = int)
        #更改数据类型，0表示用户没有对电影评分，1表示用户已经对电影评分
    '''
    第三步：构建模型
    '''
    def normalizeRatings(self):
        m, n = self.rating.shape
        #m代表电影数量，n代表用户数量
        rating_mean = np.zeros((m,1))
        #每部电影的平均得分
        rating_norm = np.zeros((m,n))
        #处理过的评分
        for i in range(m):
            idx = self.record[i,:] != 0
            #每部电影的评分，[i，:]表示每一行的所有列
            rating_mean[i] = np.mean(self.rating[i,idx])
            #第i行，评过份idx的用户的平均得分；
            #np.mean() 对所有元素求均值
            rating_norm[i,idx] -= rating_mean[i]
            #rating_norm = 原始得分-平均得分
        return rating_norm, rating_mean

    def getTrainModel(self):
        rating_norm, rating_mean = self.normalizeRatings()
        rating_norm = np.nan_to_num(rating_norm)
        #对值为NaNN进行处理，改成数值0
        self.rating_mean = np.nan_to_num(rating_mean)
        #对值为NaNN进行处理，改成数值0

        num_features = 10
        self.X_parameters = tf.Variable(tf.random_normal([self.postNo, num_features],stddev = 0.35), name = "X_parameters")
        self.Theta_parameters = tf.Variable(tf.random_normal([self.userNo, num_features],stddev = 0.35), name = "Theta_parameters")
        #tf.Variables()初始化变量
        #tf.random_normal()函数用于从服从指定正太分布的数值中取出指定个数的值，mean: 正态分布的均值。stddev: 正态分布的标准差。dtype: 输出的类型

        self.loss = 1/2 * tf.reduce_sum(((tf.matmul(self.X_parameters, self.Theta_parameters, transpose_b = True) - rating_norm) * self.record) ** 2) + 1/2 * (tf.reduce_sum(self.X_parameters ** 2) + tf.reduce_sum(self.Theta_parameters ** 2))
        #基于内容的推荐算法模型

        self.optimizer = tf.train.AdamOptimizer(1e-4)
        # https://blog.csdn.net/lenbow/article/details/52218551
        self.train = self.optimizer.minimize(self.loss)
        # Optimizer.minimize对一个损失变量基本上做两件事
        # 它计算相对于模型参数的损失梯度。
        # 然后应用计算出的梯度来更新变量。

    '''
    第四步：训练模型
    '''
    def trainningModel(self, userID, skip, limit):
        with tf.Session() as sess:
            #复用训练模型参数
            init = tf.global_variables_initializer()
            sess.run(init)
            recover = tf.train.import_meta_graph('./checkpoint_dir/MyModel.meta')
            recover.restore(sess,tf.train.latest_checkpoint('./checkpoint_dir'))
            graph = tf.get_default_graph()
            Current_X_parameters = sess.run(graph.get_tensor_by_name("X_parameters:0"))
            Current_Theta_parameters = sess.run(graph.get_tensor_by_name("Theta_parameters:0"))
            if Current_X_parameters is None:# 重新训练
                #https://www.cnblogs.com/wuzhitj/p/6648610.html
                #运行
                for i in range(200):
                    sess.run(self.train)
                Current_X_parameters, Current_Theta_parameters = sess.run([self.X_parameters, self.Theta_parameters])
                #保存训练模型参数
                saver = tf.train.Saver({"X_parameters": self.X_parameters, "Theta_parameters": self.Theta_parameters})
                saver.save(sess, './checkpoint_dir/MyModel')
        # Current_X_parameters为用户内容矩阵，Current_Theta_parameters用户喜好矩阵
        predicts = np.dot(Current_X_parameters, Current_Theta_parameters.T) + self.rating_mean
        #print(sys.getsizeof(predicts))
        # 保存到缓存
        serliaze = pickle.dumps(predicts)
        Recommand.redis.set(Recommand.recommandResultKey, serliaze)
        # dot函数是np中的矩阵乘法，np.dot(x,y) 等价于 x.dot(y)
        #errors = np.sqrt(np.sum((predicts - self.rating)**2))
        # sqrt(arr) ,计算各元素的平方根
        sortedResult = predicts[:, int(userID)].argsort()[::-1]
        # argsort()函数返回的是数组值从小到大的索引值; argsort()[::-1] 返回的是数组值从大到小的索引值
        idx = num_skip = 0
        hasNextPage = True
        nextCursor = 0
        totalCount = len(predicts)
        if skip + limit >= totalCount:
            hasNextPage = False
        if hasNextPage:
            nextCursor = skip + limit
        recommandations = []
        for i in sortedResult:
            if (skip > 0):
                if (num_skip > skip-1):
                    recommandations.append({"postID": self.posts_df.iloc[i]['postID'], "score": predicts[i,int(userID)]})
                    idx += 1
                    if idx == limit:break
                else:
                    num_skip += 1
                    continue
            else:
                recommandations.append({"postID": self.posts_df.iloc[i]['postID'], "score": predicts[i,int(userID)]})
                idx += 1
                if idx == limit:break
        return recommandations, totalCount, hasNextPage, nextCursor

    
    def getRecommand(self, userID, skip = 0, limit = 30):
        cacheRecommand = Recommand.redis.get(Recommand.recommandResultKey)
        cachePostMap = Recommand.redis.get(Recommand.postKey)
        posts_df = []
        recommandations = []
        if skip > 0 and cacheRecommand:
            predicts = pickle.loads(cacheRecommand)
            sortedResult = predicts[:, int(userID)].argsort()[::-1]
            # argsort()函数返回的是数组值从小到大的索引值; argsort()[::-1] 返回的是数组值从大到小的索引值
            idx = num_skip = 0
            hasNextPage = True
            nextCursor = 0
            totalCount = len(predicts)
            if skip + limit >= totalCount:
                hasNextPage = False
            if hasNextPage:
                nextCursor = skip + limit
            if cachePostMap:
                posts_df = pickle.loads(cachePostMap)
            else:
                posts_df = self.getPostsDf()
            for i in sortedResult:
                if (skip > 0):
                    if (num_skip > skip-1):
                        recommandations.append({"postID": posts_df.iloc[i]['postID'], "score": predicts[i,int(userID)]})
                        idx += 1
                        if idx == limit:break
                    else:
                        num_skip += 1
                        continue
                else:
                    recommandations.append({"postID": posts_df.iloc[i]['postID'], "score": predicts[i,int(userID)]})
                    idx += 1
                    if idx == limit:break
            return recommandations, totalCount, hasNextPage, nextCursor
        else:
            return self.run(userID, skip, limit)
            

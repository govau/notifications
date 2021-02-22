from time import time

from flask_redis import FlaskRedis
from flask import current_app

# expose redis exceptions so that they can be caught
from redis.exceptions import RedisError  # noqa


class RedisClient:
    redis_store = FlaskRedis()
    active = False

    def init_app(self, app):
        self.active = app.config.get('REDIS_ENABLED')
        if self.active:
            self.redis_store.init_app(app)

    def exceeded_rate_limit(self, cache_key, limit, interval, raise_exception=False):
        """
        Rate limiting.
        - Uses Redis sorted sets
        - Also uses redis "multi" which is abstracted into pipeline() by FlaskRedis/PyRedis
        - Sends all commands to redis as a group to be executed atomically

        Method:
        (1) Add event, scored by timestamp (zadd). The score determines order in set.
        (2) Use zremrangebyscore to delete all set members with a score between
            - Earliest entry (lowest score == earliest timestamp) - represented as '-inf'
                and
            - Current timestamp minus the interval
            - Leaves only relevant entries in the set (those between now and now - interval)
        (3) Count the set
        (4) If count > limit fail request
        (5) Ensure we expire the set key to preserve space

        Notes:
        - Failed requests count. If over the limit and keep making requests you'll stay over the limit.
        - The actual value in the set is just the timestamp, the same as the score. We don't store any requets details.
        - return value of pip.execute() is an array containing the outcome of each call.
            - result[2] == outcome of pipe.zcard()
        - If redis is inactive, or we get an exception, allow the request

        :param cache_key:
        :param limit: Number of requests permitted within interval
        :param interval: Interval we measure requests in
        :param raise_exception: Should throw exception
        :return:
        """
        if self.active:
            try:
                pipe = self.redis_store.pipeline()
                when = time()
                pipe.zadd(cache_key, when, when)
                pipe.zremrangebyscore(cache_key, '-inf', when - interval)
                pipe.zcard(cache_key)
                pipe.expire(cache_key, interval)
                result = pipe.execute()
                return result[2] > limit
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'rate-limit-pipeline', cache_key)
                return False
        else:
            return False

    def set(self, key, value, ex=None, px=None, nx=False, xx=False, raise_exception=False):
        if self.active:
            try:
                self.redis_store.set(key, value, ex, px, nx, xx)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'set', key)

    def incr(self, key, raise_exception=False, incr_by=1):
        if self.active:
            try:
                return self.redis_store.incr(key, amount=incr_by)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'incr', key)

    def get(self, key, raise_exception=False):
        if self.active:
            try:
                return self.redis_store.get(key)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'get', key)

        return None

    def decrement_hash_value(self, key, value, raise_exception=False):
        return self.increment_hash_value(key, value, raise_exception, incr_by=-1)

    def increment_hash_value(self, key, value, raise_exception=False, incr_by=1):
        if self.active:
            try:
                return self.redis_store.hincrby(key, value, amount=incr_by)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'increment_hash_value', key)

    def get_all_from_hash(self, key, raise_exception=False):
        if self.active:
            try:
                return self.redis_store.hgetall(key)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'get_all_from_hash', key)

    def set_hash_and_expire(self, key, values, expire_in_seconds, raise_exception=False):
        if self.active:
            try:
                self.redis_store.hmset(key, values)
                return self.redis_store.expire(key, expire_in_seconds)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'set_hash_and_expire', key)

    def expire(self, key, expire_in_seconds, raise_exception=False):
        if self.active:
            try:
                self.redis_store.expire(key, expire_in_seconds)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'expire', key)

    def delete(self, key, raise_exception=False):
        if self.active:
            try:
                self.redis_store.delete(key)
            except Exception as e:
                self.__handle_exception(e, raise_exception, 'delete', key)

    def __handle_exception(self, e, raise_exception, operation, key_name):
        current_app.logger.exception('Redis error performing {} on {}'.format(operation, key_name))
        if raise_exception:
            raise e

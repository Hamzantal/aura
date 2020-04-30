import pymongo

from core.database import Database
from core.model.member import KarmaMember
from util.config import ConfigStore


class KarmaService:

    def __init__(self):
        self._config_manager = ConfigStore()
        self._config = self._config_manager.config
        self._karma = Database(self._config['database']['host'], self._config['database']['port'],
                               self._config['database']['username'], self._config['database']['password'],
                               self._config['database']['name']).db.karma
        self._filter_query = dict(guild_id="", member_id="")
        self._channel_query = dict(guild_id="", member_id="", channel_id="")
        self._increase_karma = {"$inc": {'karma': 1}}
        self._decrease_karma = {"$inc": {'karma': -1}}

    def upsert_karma_member(self, member: KarmaMember, inc: bool):
        self._channel_query['guild_id'] = member.guild_id
        self._channel_query['member_id'] = member.member_id
        self._channel_query['channel_id'] = member.channel_id
        if inc:
            self._karma.update_one(filter=self._channel_query, update=self._increase_karma,
                                   upsert=True)
        else:
            self._karma.update_one(filter=self._channel_query, update=self._decrease_karma,
                                   upsert=False)

    def delete_all_karma(self, guild_id: str, member_id: str):
        filter_member = dict(guild_id=guild_id, member_id=member_id)
        self._karma.delete_many(filter=filter_member)

    def aggregate_member_karma(self, member: KarmaMember):
        self._filter_query['guild_id'] = member.guild_id
        self._filter_query['member_id'] = member.member_id
        pipeline = [{"$unwind": "$karma"}, {"$match": self._filter_query},
                    {"$group": {"_id": {"member_id": "$member_id"}, "karma": {"$sum": "$karma"}}}]
        print(pipeline)
        document = self._karma.aggregate(pipeline)
        if document is None:
            return 0
        else:
            for doc in document:
                return doc['karma']

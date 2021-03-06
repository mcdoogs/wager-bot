from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, Table, create_engine, or_
from sqlalchemy.orm import relationship, backref, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import datetime

engine = create_engine('sqlite:///db.sql', echo=True)

Base = declarative_base()
Session = sessionmaker(bind=engine)

session = Session()

# a class representing a single wager
class Wager(Base):
    __tablename__ = "wager"
    # Wager details
    id = Column(Integer, primary_key = True)
    guild_id = Column(Integer) # guild is basically the same thing as server
    channel_id = Column(Integer)
    message_id = Column(Integer)
    creator_id = Column(Integer, ForeignKey("user.id")) # id of user who instantiated the wager
    creator = relationship("User", back_populates="created_wagers", foreign_keys=[creator_id]) # creator object
    amount = Column(Integer)
    description = Column(String)
    created_at = Column(String, default=datetime.datetime.now())
    # Wager status
    taker_id = Column(Integer, ForeignKey("user.id")) # id of user accepting wager
    taker = relationship("User", back_populates="accepted_wagers", foreign_keys=[taker_id])
    accepted = Column(Boolean, default=False, nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    winner_id = Column(Integer, ForeignKey("user.id"))
    winner = relationship("User", back_populates="won_wagers", foreign_keys=[winner_id])
    loser_id = Column(Integer, ForeignKey("user.id"))
    loser = relationship("User", back_populates="lost_wagers", foreign_keys=[loser_id])

    def __init__(self, guild_id, channel_id, creator_id, amount, description):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id  = creator_id
        self.amount = amount
        self.description = description

    def __repr__(self):
        return f'<Wager(id={self.id}, creator_id={self.creator_id}, amount={self.amount})'

    def accept(self, taker_id):
        self.taker_id = taker_id
        self.accepted = True
        session.add(self)
        session.commit()

class User(Base):
    __tablename__ = "user"
    id = Column(Integer, primary_key = True, autoincrement = False)
    money = Column(Integer, default=0)
    created_wagers = relationship("Wager", order_by=Wager.id, back_populates="creator", foreign_keys="[Wager.creator_id]")
    accepted_wagers = relationship("Wager", order_by=Wager.id, back_populates="taker", foreign_keys="[Wager.taker_id]")
    won_wagers = relationship("Wager", order_by=Wager.id, back_populates="winner", foreign_keys="[Wager.winner_id]")
    lost_wagers = relationship("Wager", order_by=Wager.id, back_populates="loser", foreign_keys="[Wager.loser_id]")

    def __init__(self, snowflake_id, starting_money):
        self.id = snowflake_id
        self.money = starting_money

    def add_money(self, amount):
        self.money += amount
        
    def remove_money(self, amount):
        self.money -= amount

    # get the amount of money this user has outstanding in bets (created or taken bets that haven't yet been confirmed)
    def outstanding_money(self):
        query = session.query(Wager.amount).filter(or_(Wager.creator_id == self.id, Wager.taker_id == self.id)).filter(Wager.completed == False)
        query_results = query.all()
        outstanding_amount = sum([wager.amount for wager in query_results])
        return outstanding_amount

    # check to see if this user can afford an action (has enough money)
    def can_afford(self, amount):
        outstanding_amount = self.outstanding_money()
        return amount <= self.money - outstanding_amount

class Emoji(Base):
    __tablename__ = "emoji"
    id = Column(Integer, primary_key = True, autoincrement = False)
    guild_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)

    def __init__(self, emoji_id, guild_id, name):
        self.id = emoji_id
        self.guild_id = guild_id
        self.name = name

Base.metadata.create_all(engine)
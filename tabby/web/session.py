import functools
import email.utils
import logging
import typing
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, ClassVar, Literal, TypeAlias
from uuid import UUID

import discord
import pydantic
from aiohttp import web
from aiohttp.web import HTTPBadRequest, HTTPException, HTTPForbidden, HTTPUnauthorized, StreamResponse
from cryptography.fernet import InvalidToken
from discord import User
from discord.types.user import User as UserPayload
from pydantic import BaseModel, ValidationError
from yarl import URL

from ..bot import Tabby
from ..routing import Request, Response
from ..routing.exceptions import RequestValidationError, ErrorPart
from ..util import API_URL, TTLCache


LOGGER = logging.getLogger(__name__)

# 60 seconds * 60 minutes * 24 hours = 86,400 seconds (24 hours expressed in seconds)
ACCOUNT_CACHE_TTL = 60 * 60 * 24

COOKIE_NAME = "TABBY_SESSION"
SESSION_KEY = "tabby_session"
SESSION_STORAGE_KEY = "tabby_session_storage"

OAUTH_AUTHORIZATION_URL = URL("https://discord.com/oauth2/authorize")
OAUTH_TOKEN_URL = URL("https://discord.com/api/oauth2/token")

CURRENT_USER_PROFILE_URL = API_URL.join(URL("users/@me"))

# We have a few things going on here. For a start, every request is associated with a "session". This is a cookie that
# identifies a specific browser instance, and is protected by the same-origin policy.
#
# Each session cookie is an encrypted JSON payload ("the session object") that contains the session's UUID, several
# pieces of session metadata, and information about the user - such as whether they're authenticated or not.
#
# The general authorization flows looks like this:
#
# 1. The user clicks "log in with Discord" and begins Discord's OAuth flow.
#
# 2. On success, the user is redirected to the callback URL with an authorization code and a state value. The state
#    value received here is checked against the user's session cookie using a hashing/verification algorithm, to ensure
#    that the request was not forged.
#
# 3. The authorization code is exchanged for an initial access token and refresh token. This payload ("the account
#    object") is stored in memory for use in step 5.
#
# 4. The user's profile information is fetched using `/users/@me`, authorizing on their behalf using the access token
#    from step 3. This payload  ("the profile information object") is stored in memory for use in steps 5 & 6.
#
# 5. The account object is merged with the profile information object, serialized as a JSON string, and then encrypted
#    using the configured secret key. It is persisted to the database, keyed by the user's ID.
#
# 6. The user's session object is updated to reference the "account" object that was persisted to the database in step 5. The
#    profile information object from step 4 is added to the session object's contents.
#
# 7. The session object is serialized to JSON and encrypted using the configured secret key. The user's session cookie
#    is updated to contain the newer session object, and the user is redirected to the original page. They are now authorized.
#
# While this approach is *effectively* just "JWTs with extra steps", it has the benefit of ensuring that user
# credentials are encrypted at rest and never exposed on the client. Likewise, all of the information required to
# display a page is readable on the server **without** making additional API requests. This means that both the Next.JS
# application (the frontend) and the Tabby API can use this data for displaying pages.
#
# Some notes:
#
# - Sessions are **ephemeral**. They only really exist on the client, so as soon as the client clears their cookies (or
#   the cookie expires) they disappear. This makes session validation significantly easier since no requests to the
#   database need to be made.
#
# - Sessions have unique IDs precisely so that the **exact client** sending a request can be identified. This is
#   necessary from a security perspective, in order to ensure that the same client is used at both ends of the
#   authorization process. The IDs assigned to sessions are simple UUIDs; no tracking of clients is performed.
#
# - When we need to make requests on behalf of a user (i.e to view their guilds) we may need to obtain a new access
#   token. Access tokens are refreshed *only* when a request to a protected resource is made; they are are not otherwise
#   automatically refreshed. When the access token is refreshed, the user's profile information is also refreshed, and
#   the responses of both are merged to create an updated account payload. This payload is serialized as JSON, encrypted
#   using the configured secret key, and then persisted to the database, replacing the previous value when applicable.
#
# - Because the session handling machinery fetches the account payload from the database when a user has an
#   authenticated session, any changes made to the user's profile information will automatically propagate to the
#   client's session as new requests are made.
#
# And that's it!


class _ExpiredMixin:
    expires_at: datetime

    def expired(self) -> bool:
        """Whether this instance has expired."""

        return self.expires_at > discord.utils.utcnow()


class TokenResponse(BaseModel):
    """The response from the token endpoint when an access token is requested."""

    access_token: str
    """An access token used to authorize requests to Discord's API on behalf of another user."""

    token_type: str
    """The type of credentials that the access token represents. This value is primarily used when making HTTP requests
    with the `Authorization` header, and in many cases is just "Bearer".
    """

    expires_in: int
    """The number of seconds - from the time the token was issued - until the token expires."""

    refresh_token: str
    """A token that may be used to refresh the access token when/before it expires. This allows access to a protected
    resources to be renewed periodically, instead of requiring the user to repeat the authorization flow each time.
    """

    scope: str
    """The scopes that this access token"""


class AccountPayload(TokenResponse, _ExpiredMixin):
    """The information used when authorizing with Discord on a user's behalf.

    It is serialized as a JSON string, before being encrypted and persisted to the database.
    """

    user: UserPayload
    """The user that this access token represents. This data is also placed in the session cookie."""

    obtained_at: datetime
    """The time that this access token was obtained."""

    @property
    def expires_at(self) -> datetime:
        return self.obtained_at.astimezone(timezone.utc) + timedelta(seconds=self.expires_in)


class DefaultSessionPayload(BaseModel, _ExpiredMixin):
    """A bare session with no user information."""

    uuid: UUID
    """The unique ID of this session. This serves as a security mechanism to ensure that the client that initiates an
    authorization flow is the same client that receives the completion callback."""

    issued_at: datetime
    """The time this session was originally issued."""

    expires_at: datetime
    """The time this session will expire. When a session is actively in use, its expiry date is updated periodically so
    that a user is not logged out unnecessarily.
    """


class UserSessionPayload(DefaultSessionPayload):
    """A session authorized by a user."""

    user: UserPayload
    """The user associated with this session."""


SessionPayload: TypeAlias = UserSessionPayload | DefaultSessionPayload


class Session:
    """A high-level API for interacting with the user's session."""

    authorized: ClassVar[Literal[False]] = False
    """Whether this session has been authenticated by a user."""

    _storage: "SessionStorage"
    _bot: Tabby

    details: DefaultSessionPayload

    def __init__(self, storage: "SessionStorage", details: DefaultSessionPayload) -> None:
        self._storage = storage
        self._bot = storage._bot

        self.details = details

    @property
    def uuid(self) -> UUID:
        """The unique ID of this session."""

        return self.details.uuid

    @functools.cached_property
    def state(self) -> str:
        """The state value associated with this session.

        This is used as a security measure to verify that a request was not intercepted.
        """

        return hex(hash(self.uuid))

    @property
    def authorization_url(self) -> URL:
        """Retrieve the URL that should be used to authorize with Discord."""

        parameters = {
            "response_type": "code",
            "client_id": self._bot.config.bot.client_id,
            "scope": "identify guilds",
            "state": self.state,
            "redirect_uri": self._bot.config.web.redirect_uri,
            # Don't make the user authorize the application again unnecessarily
            "prompt": "none",
        }

        return OAUTH_AUTHORIZATION_URL.with_query(parameters)

    @classmethod
    async def from_request(cls, request: Request) -> "Session":
        """Retrieve the session associated with a particular request."""

        return get_session(request)

    def extend_lifetime(self) -> "Session":
        """Extend the lifetime of this session, if it hasn't already expired.

        This method mutates the session in-place, and returns the instance for fluid-style chaining.
        """

        if not self.details.expired:
            self.details.expires_at = discord.utils.utcnow() + timedelta(days=7)

        return self

    def serialize(self) -> str:
        """Serialize the session payload using the configured secret key."""

        return self._bot.config.web.secret_key.serialize(self.details).decode()


class AuthorizedSession(Session):
    authorized: ClassVar[Literal[True]] = True

    account: AccountPayload
    details: DefaultSessionPayload | UserSessionPayload

    @classmethod
    async def complete_authorization(cls, request: Request, *, code: str, state: str) -> "AuthorizedSession":
        """Complete authorization for `request` and authorize the user's session.

        `code` is the authorization code to exchange for an access token.
        `state` is the authorization state from the oauth callback, which will be used to verify the authorization request.
        """

        existing = get_session(request)

        if existing.authorized:
            raise HTTPBadRequest(text="session already authorized")

        if existing.state != state:
            raise HTTPForbidden(text="mismatched authorization state; was the request intercepted?")

        authorized = cls(existing._storage, existing.details)
        await authorized._refresh_account(code=code)

        request[SESSION_KEY] = authorized

        return authorized

    @classmethod
    async def from_request(cls, request: Request) -> "AuthorizedSession":
        session = get_session(request)

        if not session.authorized:
            raise HTTPUnauthorized(text="Authorization required")

        assert isinstance(session, AuthorizedSession)

        return session

    async def _refresh_account(self, *, code: str | None = None):
        if code:
            should_refresh = True
            getter = self._get_token(code=code)
        else:
            until_expiry = self.account.expires_at - discord.utils.utcnow()
            should_refresh = until_expiry < timedelta(days=1)
            getter = self._get_token(refresh_token=self.account.refresh_token)

        if not should_refresh:
            return

        token_payload = await getter
        user_payload = await self._get_profile(token_payload.access_token)

        obtained_at = discord.utils.utcnow()
        account_payload = AccountPayload(
            **token_payload.dict(),
            obtained_at=obtained_at,
            user=user_payload,
        )

        user_id = int(user_payload["id"])
        encrypted = self._bot.config.web.secret_key.serialize(account_payload)

        query = """
            INSERT INTO tabby.user_accounts(user_id, account_info)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET account_info = excluded.account_info
        """

        async with self._bot.db() as connection:
            await connection.execute(query, user_id, encrypted)

        self.account = account_payload
        self.details = UserSessionPayload(
            **self.details.dict(),
            user=user_payload,
        )

        # ... and update the cache, so that we don't re-fetch any of this information on subsequent requests
        # unnecessarily
        self._storage._cached_accounts[user_id] = account_payload

    async def _get_profile(self, token: str) -> UserPayload:
        headers = {"authorization": f"Bearer {token}"}

        async with self._bot.session.get(CURRENT_USER_PROFILE_URL, headers=headers) as response:
            payload = await response.json()

            if not response.ok:
                raise RuntimeError("request failed")

        return pydantic.parse_obj_as(UserPayload, payload)

    @typing.overload
    async def _get_token(self, *, code: str):
        ...

    @typing.overload
    async def _get_token(self, *, refresh_token: str):
        ...

    async def _get_token(self, *, code: str | None = None, refresh_token: str | None = None) -> TokenResponse:
        if code and refresh_token:
            raise TypeError("`code` and `refresh_token` parameters are mutually exclusive")
        elif not code and not refresh_token:
            raise TypeError("one of `code` or `refresh_token` must be passed")

        data = {
            "client_id": self._bot.config.bot.client_id,
            "client_secret": self._bot.config.bot.client_secret,
        }

        if code:
            data["grant_type"] = "authorization_code"
            data["code"] = code
            data["redirect_uri"] = self._bot.config.web.redirect_uri
        else:
            assert refresh_token is not None

            data["grant_type"] = "refresh_token"
            data["refresh_token"] = refresh_token

        headers = {"content-type": "application/x-www-form-urlencoded"}

        async with self._bot.session.post(OAUTH_TOKEN_URL, data=data, headers=headers) as response:
            payload = await response.json()

        return TokenResponse.parse_obj(payload)

    async def get_user(self) -> User:
        """Retrieve the `User` object associated with this session.
        The access token may need to be refreshed, which is why this method is a coroutine.
        """

        await self._refresh_account()

        assert isinstance(self.details, UserSessionPayload)

        return User(state=self._bot._connection, data=self.details.user)

    async def get_access_token(self) -> str:
        """Retrieve the access token associated with this session.
        The access token may need to be refreshed, which is why this method is a coroutine.
        """

        await self._refresh_account()

        return self.account.access_token


class SessionStorage:
    """An aiohttp middleware for handling user sessions.

    This class is responsible for making sessions available to handlers, as well as updating session cookies in
    responses and ensuring that profile information for authenticated users remains current.
    """

    _bot: Tabby
    _cached_accounts: TTLCache[int, AccountPayload]

    def __init__(self, bot: Tabby) -> None:
        self._bot = bot
        self._cached_accounts = TTLCache(expiry=ACCOUNT_CACHE_TTL)

        # Necessary to make class instances usable as middleware
        web.middleware(self)

    async def __call__(
        self,
        request: Request,
        handler: Callable[[Request], Awaitable[StreamResponse]]
    ) -> StreamResponse:
        request[SESSION_STORAGE_KEY] = self
        request[SESSION_KEY] = (await self.get_session(request)).extend_lifetime()

        should_raise = False

        try:
            response = await handler(request)
        except HTTPException as error:
            response = error
            should_raise = True

        if not isinstance(response, (StreamResponse, HTTPException)):
            raise TypeError(f"expected a StreamResponse subclass, but found {type(response)}")
        # This must've been a WS/streaming response. We can't do much in that case.
        elif not isinstance(response, (Response, HTTPException)):
            return response

        if response.prepared:
            raise RuntimeError("can't update session for a prepared response")

        # We don't reuse the session from earlier since the handler might update it or replace it in some way. If that's
        # the case, we should honour their changes to avoid any surprises.
        session = request[SESSION_KEY]
        if not isinstance(session, Session):
            raise TypeError(f"expected a Session instance, but found {type(session)}")

        # Cookie expiries use HTTP date syntax, so we need to format the session's expiry date. In true Python fashion,
        # the method we need for this is in the `email` module.
        expires = email.utils.format_datetime(session.details.expires_at, usegmt=True)

        response.set_cookie(COOKIE_NAME, session.serialize(), expires=expires)

        # We need to re-raise the exception instead of returning it directly. Returning `HTTPException` subclasses as
        # responses is deprecated and won't behave the way we want it to in the presence of an error boundary/error
        # handling elsewhere.
        if should_raise:
            assert isinstance(response, HTTPException)

            raise response

        return response

    async def create_session(self) -> Session:
        """Create a new, unauthenticated session."""

        issued_at = discord.utils.utcnow()
        payload = DefaultSessionPayload(
            uuid=uuid.uuid4(),
            issued_at=issued_at,
            expires_at=issued_at + timedelta(days=7),
        )

        return Session(self, payload)

    async def get_session(self, request: Request) -> Session | AuthorizedSession:
        """Retrieve the session associated with this request.

        If a session for the user does not exist, a new one is created.
        """

        session_cookie = request.cookies.get(COOKIE_NAME)

        if session_cookie is None:
            LOGGER.info("no session exists for this request, creating a new one")

            return await self.create_session()

        try:
            session_payload = self._bot.config.web.secret_key.deserialize(SessionPayload, session_cookie.encode())
        except ValidationError as error:
            raise RequestValidationError(
                part=ErrorPart.cookies,
                original=error,
                message=f"invalid schema in the {COOKIE_NAME} cookie's encrypted payload",
            )
        except (InvalidToken, ValueError) as error:
            raise HTTPBadRequest(text=f"invalid {COOKIE_NAME} cookie: {error}") from None

        LOGGER.info("found an existing session for this request: %s", session_payload.dict())

        if not isinstance(session_payload, UserSessionPayload):
            return Session(self, session_payload)

        user_id = int(session_payload.user["id"])

        if user_id not in self._cached_accounts:
            query = """
                SELECT account_info
                FROM tabby.user_accounts
                WHERE user_id = $1
            """

            async with self._bot.db() as connection:
                encrypted_payload = await connection.fetchval(query, user_id)

            assert encrypted_payload is not None

            self._cached_accounts[user_id] = self._bot.config.web.secret_key.deserialize(
                AccountPayload,
                encrypted_payload,
            )

        # The user information in the session cookie needs to be updated; it may have changed between requests.
        account_info = self._cached_accounts[user_id]
        session_payload.user = account_info.user

        session = AuthorizedSession(self, session_payload)
        session.account = account_info

        return session


def get_session(request: Request) -> Session | AuthorizedSession:
    """Retrieve the session associated with a request."""

    if SESSION_KEY not in request:
        raise RuntimeError("`SessionStorage` not added as middleware")

    return request[SESSION_KEY]

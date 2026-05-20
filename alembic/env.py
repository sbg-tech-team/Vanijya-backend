from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context  # type: ignore

# Import all models so Alembic autogenerate can detect them
from app.core.database.base import Base
from app.modules.auth.models import UserSession  # noqa: F401
from app.modules.profile.models import (  # noqa: F401
    User,
    Profile,
    Role,
    Commodity,
    Interest,
    Profile_Commodity,
    Profile_Interest,
)
from app.modules.verification.models import VerificationRecord  # noqa: F401
from app.modules.post.models import (  # noqa: F401
    Post,
    PostCategory,
    PostView,
    PostLike,
    PostComment,
    PostShare,
    PostSave,
)
from app.modules.groups.models import (  # noqa: F401
    Group,
    GroupMember,
    GroupActivityCache,
    GroupEmbedding,
)
from app.modules.news.models import (  # noqa: F401
    NewsSource,
    NewsArticle,
    NewsEngagement,
    UserClusterTaste,
    NewsTrending,
)
from app.modules.chat.data.models import (  # noqa: F401
    Conversation,
    ConversationMember,
    Message,
    ChatAttachment,
)
from app.modules.safety.models import (  # noqa: F401
    UserBlock,
    UserReport,
)

from app.core.config import settings

# Alembic Config object
config = context.config

# Set the DB URL from our settings (overrides the blank value in alembic.ini)
config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    Only manage tables that are defined in our models.
    This prevents Alembic from dropping existing unrelated tables
    (e.g. old 'Users', 'user_connections', 'message_requests').
    """
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"sslmode": "require"},
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

import logging
import os

from dotenv import load_dotenv

from bot_helper import BotHelper, default_max_tokens
from telegram_bot import ChatBotTelegramBot

def main():
    # Read .env file
    load_dotenv()

    # Setup logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Check if the required environment variables are set
    required_values = ['TELEGRAM_BOT_TOKEN', 'ANTHROPIC_API_KEY']
    missing_values = [value for value in required_values if os.environ.get(value) is None]
    if len(missing_values) > 0:
        logging.error(f'The following environment values are missing in your .env: {", ".join(missing_values)}')
        exit(1)

    # Setup configurations
    model = os.environ.get('ANTHROPIC_MODEL', 'claude-3-5-sonnet-20241022')
    max_tokens_default = default_max_tokens(model=model)

    bot_config = {
        'api_key': os.environ['ANTHROPIC_API_KEY'],
        'show_usage': os.environ.get('SHOW_USAGE', 'false').lower() == 'true',
        'stream': os.environ.get('STREAM', 'true').lower() == 'true',
        'proxy': os.environ.get('PROXY', None),
        'max_history_size': int(os.environ.get('MAX_HISTORY_SIZE', 15)),
        'max_conversation_age_minutes': int(os.environ.get('MAX_CONVERSATION_AGE_MINUTES', 180)),
        'assistant_prompt': os.environ.get('ASSISTANT_PROMPT', 'You are Claude, a helpful AI assistant created by Anthropic.'),
        'max_tokens': int(os.environ.get('MAX_TOKENS', max_tokens_default)),
        'temperature': float(os.environ.get('TEMPERATURE', 0.7)),
        'model': model,
        'top_k': int(os.environ.get('TOP_K', 1)),
        'top_p': float(os.environ.get('TOP_P', 0.7)),
        'system_prompt': os.environ.get('SYSTEM_PROMPT', None),
        'bot_language': os.environ.get('BOT_LANGUAGE', 'en'),
        'metadata': {
            'user_id': os.environ.get('USER_ID', 'telegram_user'),
            'conversation_id': os.environ.get('CONVERSATION_ID', 'default')
        }
    }

    telegram_config = {
        'token': os.environ['TELEGRAM_BOT_TOKEN'],
        'admin_user_ids': os.environ.get('ADMIN_USER_IDS', '-'),
        'allowed_user_ids': os.environ.get('ALLOWED_TELEGRAM_USER_IDS', '*'),
        'enable_quoting': os.environ.get('ENABLE_QUOTING', 'true').lower() == 'true',
        'stream': os.environ.get('STREAM', 'true').lower() == 'true',
        'proxy': os.environ.get('PROXY', None),
        'budget_period': os.environ.get('BUDGET_PERIOD', 'monthly').lower(),
        'user_budgets': os.environ.get('USER_BUDGETS', os.environ.get('MONTHLY_USER_BUDGETS', '10.0')),
        'guest_budget': float(os.environ.get('GUEST_BUDGET', os.environ.get('MONTHLY_GUEST_BUDGET', '10.0'))),
        'bot_language': os.environ.get('BOT_LANGUAGE', 'en'),
        'token_price': float(os.environ.get('TOKEN_PRICE', 0.002)),
        'max_message_length': int(os.environ.get('MAX_MESSAGE_LENGTH', 4096)),
        'enable_image_input': os.environ.get('ENABLE_IMAGE_INPUT', 'true').lower() == 'true',
        'message_timeout': int(os.environ.get('MESSAGE_TIMEOUT', 120))
    }

    bot_helper = BotHelper(config=bot_config)
    telegram_bot = ChatBotTelegramBot(config=telegram_config, bot_helper=bot_helper)
    telegram_bot.run()


if __name__ == '__main__':
    main()

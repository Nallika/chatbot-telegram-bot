from __future__ import annotations
import datetime
import logging
import anthropic
import httpx
import os
import json
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# Load translations
parent_dir_path = os.path.join(os.path.dirname(__file__), os.pardir)
translations_file_path = os.path.join(parent_dir_path, 'translations.json')
with open(translations_file_path, 'r', encoding='utf-8') as f:
    translations = json.load(f)

def default_max_tokens(model: str) -> int:
    return 8192 if "sonet" in model else 4000

def localized_text(key, bot_language):
    """
    Return translated text for a key in specified bot_language.
    Keys and translations can be found in the translations.json.
    """
    try:
        return translations[bot_language][key]
    except KeyError:
        logging.warning(f"No translation available for bot_language code '{bot_language}' and key '{key}'")
        # Fallback to English if the translation is not available
        if key in translations['en']:
            return translations['en'][key]
        else:
            logging.warning(f"No english definition found for key '{key}' in translations.json")
            # return key as text
            return key

class BotHelper:
    def __init__(self, config: dict):
        http_client = httpx.AsyncClient(proxy=config['proxy']) if 'proxy' in config else None
        self.client = anthropic.AsyncAnthropic(
            api_key=config['api_key'],
            http_client=http_client
        )
        self.config = config
        self.conversations: dict[int: list] = {}
        self.conversations_vision: dict[int: bool] = {}
        self.last_updated: dict[int: datetime] = {}

    def get_conversation_stats(self, chat_id: int) -> tuple[int, int]:
        if chat_id not in self.conversations:
            self.reset_chat_history(chat_id)
        return len(self.conversations[chat_id]), self.__count_tokens(self.conversations[chat_id])

    async def get_chat_response(self, chat_id: int, query: str) -> tuple[str, str]:
        response = await self.__common_get_chat_response(chat_id, query)
        answer = response.content[0].text
        self.__add_to_history(chat_id, role="assistant", content=answer)

        bot_language = self.config['bot_language']
        if self.config['show_usage']:
            tokens_used = self.__count_tokens(self.conversations[chat_id])
            answer += f"\n\n---\n💰 {tokens_used} {localized_text('stats_tokens', bot_language)}"

        return answer, tokens_used

    async def get_chat_response_stream(self, chat_id: int, query: str):
        response = await self.__common_get_chat_response(chat_id, query, stream=True)
        
        answer = ''
        async for chunk in response:
            if chunk.type == "content_block_delta":
                answer += chunk.delta.text
                yield answer, 'not_finished'
        
        answer = answer.strip()
        self.__add_to_history(chat_id, role="assistant", content=answer)
        tokens_used = str(self.__count_tokens(self.conversations[chat_id]))

        if self.config['show_usage']:
            answer += f"\n\n---\n💰 {tokens_used} {localized_text('stats_tokens', self.config['bot_language'])}"

        yield answer, tokens_used

    @retry(
        reraise=True,
        retry=retry_if_exception_type(anthropic.RateLimitError),
        wait=wait_fixed(20),
        stop=stop_after_attempt(3)
    )
    async def __common_get_chat_response(self, chat_id: int, query: str, stream=False):
        bot_language = self.config['bot_language']
        try:
            if chat_id not in self.conversations or self.__max_age_reached(chat_id):
                self.reset_chat_history(chat_id)

            self.last_updated[chat_id] = datetime.datetime.now()
            self.__add_to_history(chat_id, role="user", content=query)

            # Handle history management
            token_count = self.__count_tokens(self.conversations[chat_id])
            if (token_count + self.config['max_tokens'] > self.__max_model_tokens() or 
                len(self.conversations[chat_id]) > self.config['max_history_size']):
                try:
                    summary = await self.__summarise(self.conversations[chat_id][:-1])
                    self.reset_chat_history(chat_id, self.conversations[chat_id][0]['content'])
                    self.__add_to_history(chat_id, role="assistant", content=summary)
                    self.__add_to_history(chat_id, role="user", content=query)
                except Exception as e:
                    logging.warning(f'Error summarising chat history: {str(e)}. Truncating instead...')
                    self.conversations[chat_id] = self.conversations[chat_id][-self.config['max_history_size']:]

            # Extract system message and convert history format
            system_message = next((msg['content'] for msg in self.conversations[chat_id] if msg['role'] == 'system'), None)
            messages = []
            for msg in self.conversations[chat_id]:
                if msg['role'] in ['user', 'assistant']:
                    messages.append({"role": msg['role'], "content": msg['content']})

            return await self.client.messages.create(
                model=self.config['model'],
                messages=messages,
                system=system_message,  # Pass system message separately
                temperature=self.config['temperature'],
                max_tokens=self.config['max_tokens'],
                stream=stream
            )

        except anthropic.RateLimitError as e:
            raise e
        except anthropic.BadRequestError as e:
            raise Exception(f"⚠️ _{localized_text('invalid_request', bot_language)}._ ⚠️\n{str(e)}") from e
        except Exception as e:
            raise Exception(f"⚠️ _{localized_text('error', bot_language)}._ ⚠️\n{str(e)}") from e

    def reset_chat_history(self, chat_id, content=''):
        if content == '':
            content = self.config['assistant_prompt']
        self.conversations[chat_id] = [{"role": "system", "content": content}]
        self.conversations_vision[chat_id] = False

    def __max_age_reached(self, chat_id) -> bool:
        if chat_id not in self.last_updated:
            return False
        last_updated = self.last_updated[chat_id]
        now = datetime.datetime.now()
        max_age_minutes = self.config['max_conversation_age_minutes']
        return last_updated < now - datetime.timedelta(minutes=max_age_minutes)

    def __add_to_history(self, chat_id, role, content):
        self.conversations[chat_id].append({"role": role, "content": content})

    async def __summarise(self, conversation) -> str:
        response = await self.client.messages.create(
            model=self.config['model'],
            system="Summarize this conversation in 700 characters or less",
            messages=[{"role": "user", "content": str(conversation)}],
            temperature=0.4,
            max_tokens=1000
        )
        return response.content[0].text

    def __max_model_tokens(self):
        return default_max_tokens(self.config['model'])

    def __count_tokens(self, messages) -> int:
        total_tokens = 0
        for message in messages:
            # Rough estimation since Claude doesn't provide exact token counting
            total_tokens += len(message['content'].split()) * 1.3
        return int(total_tokens)
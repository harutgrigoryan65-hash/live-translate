# Security

Do not commit local secrets or personal knowledge files.

Ignored private files:

- `settings.json`
- `knowledge_base.json`
- `.env`

If an API key was committed or shared, revoke it in the provider console and create a new key.

Gem Translate can send audio transcripts, prompts, and selected RAG chunks to the configured model provider. Review your provider settings and privacy requirements before using this in real interviews.

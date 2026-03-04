import asyncio
import os
import sys
import json
import logging
import aiohttp
import argparse
from aiohttp import web
from .client import Client, LOGGER, BASE_URL, DEFAULT_VOICE

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s: %(message)s')
HTTP_PORT = int(os.getenv("HTTP_PORT") or 80)

async def run_web(client: Client):
    async def get_models(request):
        models = [
            {"id": "zai-tts"},
        ]
        user_id = request.query.get("user_id")
        token = request.headers.get("Authorization")
        data = {
            "data": models,
            "voices": await client.get_voices(token=token, user_id=user_id),
        }
        return web.json_response(data)

    async def audio_speech(request):
        payload = await request.json() if request.content_type == "application/json" else request.query
        resp = web.StreamResponse(status=200, headers={
            aiohttp.hdrs.CONTENT_TYPE: "audio/wav",
        })
        await resp.prepare(request)
        async for chunk in client.audio_speech(payload):
            LOGGER.debug("Audio bytes (%s): %s", len(chunk), chunk[:64].hex())
            await resp.write(chunk)

        await resp.write_eof()
        return resp

    @web.middleware
    async def cors_auth_middleware(request, handler):
        request.response_factory = lambda: web.StreamResponse()
        response = await handler(request)
        response.headers[aiohttp.hdrs.ACCESS_CONTROL_ALLOW_ORIGIN] = "*"
        response.headers[aiohttp.hdrs.ACCESS_CONTROL_ALLOW_METHODS] = "GET, POST, OPTIONS"
        response.headers[aiohttp.hdrs.ACCESS_CONTROL_ALLOW_HEADERS] = "Content-Type, Authorization"
        return response

    app = web.Application(logger=LOGGER, middlewares=[cors_auth_middleware])
    app.router.add_get("/v1/models", get_models)
    app.router.add_route("*", "/v1/audio/speech", audio_speech)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    print("======== Running on {} ========".format(site.name))
    await asyncio.Event().wait()

async def async_main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--list-voices", help="Lists available voices", action="store_true")
    parser.add_argument("-t", "--text", help="Text content")
    parser.add_argument("-f", "--file", help="Same as --text but read from file")
    parser.add_argument("-o", "--output", help="Output to wav file")
    parser.add_argument("-v", "--voice", help=f"Voice for TTS. Default: {DEFAULT_VOICE}", default=DEFAULT_VOICE)
    parser.add_argument("--speed", help="Speed", default="1")
    parser.add_argument("--volume", help="Volume", default="1")
    args = parser.parse_args()
    if args.file in ("-", "/dev/stdin"):
        args.text = sys.stdin.read()
    elif args.file:
        with open(args.file, encoding="utf-8") as file:
            args.text = file.read()

    async with aiohttp.ClientSession(base_url=BASE_URL) as session:
        client = Client(session)
        if args.list_voices:
            print(json.dumps(await client.get_voices(), indent=4, ensure_ascii=False))
        elif args.text:
            payload = {
                "input": args.text,
                "voice": args.voice,
                "speed": args.speed,
                "volume": args.volume,
            }
            try:
                audio_file = (
                    open(args.output, "wb")
                    if args.output not in [None, "", "-"]
                    else sys.stdout.buffer
                )
                async for chunk in client.audio_speech(payload):
                    audio_file.write(chunk)
            finally:
                if audio_file is not sys.stdout.buffer:
                    audio_file.close()
        else:
            await run_web(client)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()

"""Command-line interface for Suno Song Downloaderist.

Provides all user-facing commands: login, logout, download, list, info, dashboard, config.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from suno_downloaderist import __app_name__, __version__
from suno_downloaderist.config import AppConfig, load_config, reset_config, save_config
from suno_downloaderist.utils import (
    console,
    format_bytes,
    format_duration,
    format_eta,
    format_speed,
    setup_logging,
)

logger = logging.getLogger(__name__)


def _parse_datetime(value: str) -> datetime:
    """Parse a datetime string supporting multiple formats.

    Supports:
        - YYYY-MM-DD
        - YYYY-MM-DD HH:MM
        - YYYY-MM-DDTHH:MM
        - YYYY-MM-DD HH:MM:SS

    Args:
        value: Datetime string to parse.

    Returns:
        Parsed datetime in UTC.

    Raises:
        click.BadParameter: If format is not recognized.
    """
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise click.BadParameter(
        f"Invalid date format: '{value}'. "
        "Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM'."
    )


class DateTimeParamType(click.ParamType):
    """Click parameter type for datetime strings with hour/minute precision."""

    name = "datetime"

    def convert(self, value: str, param: click.Parameter | None, ctx: click.Context | None) -> datetime:
        if isinstance(value, datetime):
            return value
        try:
            return _parse_datetime(value)
        except click.BadParameter as exc:
            self.fail(str(exc), param, ctx)


DATETIME_TYPE = DateTimeParamType()


def _require_session() -> tuple:
    """Check for a valid saved session.

    Returns:
        Tuple of (SessionManager, session_data).

    Raises:
        click.ClickException: If no valid session found.
    """
    from suno_downloaderist.auth.session import SessionManager

    manager = SessionManager()
    if not manager.is_session_valid():
        raise click.ClickException(
            "No active session found. Please run 'suno-dl login' first."
        )
    session_data = manager.load_session()
    if session_data is None:
        raise click.ClickException(
            "Session could not be loaded. Please run 'suno-dl login' again."
        )
    return manager, session_data


async def _build_client(session_data) -> tuple:
    """Build an authenticated SunoClient from session data.

    Args:
        session_data: Loaded session data with Clerk cookie.

    Returns:
        Tuple of (ClerkTokenManager, SunoClient).
    """
    from suno_downloaderist.auth.clerk import ClerkTokenManager
    from suno_downloaderist.api.client import SunoClient

    token_manager = ClerkTokenManager()
    await token_manager.exchange_cookie_for_session(session_data.cookie)
    await token_manager.start_refresh_loop()

    client = SunoClient(token_manager=token_manager)
    return token_manager, client


# ─── CLI Group ──────────────────────────────────────────────────────────────

@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.version_option(version=__version__, prog_name=__app_name__)
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Suno Song Downloaderist -- Download and preserve your Suno AI music library."""
    setup_logging(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["config"] = load_config()


# ─── LOGIN ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--manual", is_flag=True, default=False,
    help="Paste your session cookie manually instead of opening a browser.",
)
def login(manual: bool) -> None:
    """Open a browser window to log into Suno and save your session."""

    if manual:
        _do_manual_login()
    else:
        _do_browser_login()


def _do_manual_login() -> None:
    """Manual login: user pastes their __client cookie from DevTools."""
    console.print(
        Panel(
            "[bold]Manual Login[/bold]\n\n"
            "1. Open [link=https://suno.com]suno.com[/link] in your browser and make sure you're logged in.\n"
            "2. Press [bold]F12[/bold] to open DevTools.\n"
            "3. Click the [bold]Application[/bold] tab (Chrome) or [bold]Storage[/bold] tab (Firefox).\n"
            "4. In the left sidebar, click [bold]Cookies[/bold] > [bold]https://suno.com[/bold].\n"
            "5. Find the cookie named [bold yellow]__client[/bold yellow] and copy its [bold]Value[/bold].\n"
            "6. Paste it below.",
            title="Manual Authentication",
            border_style="purple",
        )
    )

    cookie_value = click.prompt(
        "\nPaste your __client cookie value",
        hide_input=False,
    ).strip()

    if not cookie_value:
        console.print("[bold red]No cookie provided.[/bold red]")
        raise click.Abort()

    if len(cookie_value) < 50:
        console.print("[bold red]That doesn't look right — the __client cookie is usually very long.[/bold red]")
        raise click.Abort()

    # Verify it works
    async def _verify_and_save():
        import httpx
        from suno_downloaderist.auth.browser import SessionData
        from suno_downloaderist.auth.session import SessionManager
        import time

        console.print("\n[dim]Verifying cookie...[/dim]")

        url = "https://clerk.suno.com/v1/client"
        headers = {"Cookie": f"__client={cookie_value}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=10.0)

        if response.status_code != 200:
            console.print(f"[bold red]Clerk API returned {response.status_code}. Cookie might be invalid.[/bold red]")
            raise click.Abort()

        data = response.json()
        response_data = data.get("response", data)
        sessions = response_data.get("sessions", [])
        active = [s for s in sessions if s.get("status") == "active"]

        if not active and not response_data.get("last_active_session_id"):
            console.print("[bold red]No active sessions found for this cookie. Are you logged in?[/bold red]")
            raise click.Abort()

        session_data = SessionData(
            cookie=cookie_value,
            session_id=None,
            timestamp=time.time(),
            user_agent="manual-login",
        )

        manager = SessionManager()
        manager.save_session(session_data)

        console.print(
            f"\n[bold green]Login successful![/bold green]\n"
            f"Session saved and encrypted locally.\n"
            f"Session expires in 7 days. Run [bold]suno-dl login --manual[/bold] again to refresh."
        )

    try:
        asyncio.run(_verify_and_save())
    except KeyboardInterrupt:
        console.print("\n[yellow]Login cancelled.[/yellow]")
    except click.exceptions.Abort:
        raise
    except Exception as exc:
        console.print(f"\n[bold red]Verification failed:[/bold red] {exc}")
        raise click.Abort()


def _do_browser_login() -> None:
    """Browser login: Playwright opens Chrome for interactive login."""
    console.print(
        Panel(
            "[bold]Suno Login[/bold]\n\n"
            "A browser window will open to [link=https://suno.com]suno.com[/link].\n"
            "Log in with your account, and we'll capture the session automatically.\n"
            "Your credentials are [bold green]never stored[/bold green] — only an encrypted session token.\n\n"
            "[dim]Tip: If this doesn't work, try:[/dim] [bold]suno-dl login --manual[/bold]",
            title="Authentication",
            border_style="purple",
        )
    )

    async def _do_login():
        from suno_downloaderist.auth.browser import BrowserAuthenticator
        from suno_downloaderist.auth.session import SessionManager

        authenticator = BrowserAuthenticator()
        console.print("\n[dim]Opening browser...[/dim]")
        session_data = await authenticator.authenticate()

        manager = SessionManager()
        manager.save_session(session_data)

        console.print(
            f"\n[bold green]Login successful![/bold green]\n"
            f"Session saved and encrypted locally.\n"
            f"Session expires in 7 days. Run [bold]suno-dl login[/bold] again to refresh."
        )

    try:
        asyncio.run(_do_login())
    except KeyboardInterrupt:
        console.print("\n[yellow]Login cancelled.[/yellow]")
    except Exception as exc:
        console.print(f"\n[bold red]Login failed:[/bold red] {exc}")
        console.print("[dim]Try [bold]suno-dl login --manual[/bold] instead.[/dim]")
        raise click.Abort()


# ─── LOGOUT ─────────────────────────────────────────────────────────────────

@cli.command()
def logout() -> None:
    """Clear your saved session and log out."""
    from suno_downloaderist.auth.session import SessionManager

    manager = SessionManager()

    if not manager.is_session_valid():
        console.print("[yellow]No active session to clear.[/yellow]")
        return

    if not click.confirm("Are you sure you want to log out?"):
        return

    manager.clear_session()
    console.print("[green]✅ Session cleared. You are logged out.[/green]")


# ─── DOWNLOAD ───────────────────────────────────────────────────────────────

@cli.command()
@click.option(
    "--output", "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for downloads. Default: ~/Music/SunoDownloaderist/",
)
@click.option(
    "--format", "-f", "formats",
    type=click.Choice(["mp3", "wav", "mp4", "all"], case_sensitive=False),
    multiple=True,
    default=None,
    help="Download format(s). Can be specified multiple times. Default: mp3.",
)
@click.option("--workers", "-w", type=int, default=None, help="Number of parallel workers (1-16).")
@click.option("--skip-existing/--no-skip", default=None, help="Skip already-downloaded files.")
@click.option("--liked-only", is_flag=True, default=False, help="Only download liked/thumbs-up songs.")
@click.option("--since", type=DATETIME_TYPE, default=None, help="Download songs created after this date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM').")
@click.option("--until", type=DATETIME_TYPE, default=None, help="Download songs created before this date.")
@click.option("--search", type=str, default=None, help="Filter by title (substring match).")
@click.option("--min-plays", type=int, default=None, help="Only download songs with at least this many plays.")
@click.option("--include-video/--no-video", default=None, help="Include MP4 video downloads.")
@click.option("--rescan", is_flag=True, default=False, help="Force a full library rescan instead of using cached index.")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be downloaded without downloading.")
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
@click.pass_context
def download(
    ctx: click.Context,
    output: Path | None,
    formats: tuple[str, ...] | None,
    workers: int | None,
    skip_existing: bool | None,
    liked_only: bool,
    since: datetime | None,
    until: datetime | None,
    search: str | None,
    min_plays: int | None,
    include_video: bool | None,
    rescan: bool,
    dry_run: bool,
    yes: bool,
) -> None:
    """Download your Suno song library.

    Downloads songs with all metadata, lyrics, cover art, and ID3 tags.
    Songs are organized into folders by title, with all versions grouped together.

    Examples:

        suno-dl download                          # Download everything as MP3

        suno-dl download -f mp3 -f mp4            # Download MP3 + MP4

        suno-dl download -f all                   # Download all formats

        suno-dl download --liked-only             # Only liked songs

        suno-dl download -w 8                     # Fast download with 8 parallel workers

        suno-dl download --since "2026-08-01"     # Songs from August 2026

        suno-dl download -o ~/Desktop/MySunoSongs # Custom output folder
    """
    config: AppConfig = ctx.obj["config"]

    # Apply CLI overrides to config
    if output is not None:
        config.output_dir = output.expanduser()
    if workers is not None:
        config.workers = max(1, min(16, workers))
    if skip_existing is not None:
        config.skip_existing = skip_existing
    if include_video is not None:
        config.download_mp4 = include_video

    # Parse format flags
    if formats:
        format_set = set(formats)
        if "all" in format_set:
            config.download_mp3 = True
            config.download_wav = True
            config.download_mp4 = True
        else:
            config.download_mp3 = "mp3" in format_set
            config.download_wav = "wav" in format_set
            config.download_mp4 = "mp4" in format_set

    # Ensure at least one format is selected
    if not (config.download_mp3 or config.download_wav or config.download_mp4):
        config.download_mp3 = True  # Fallback to MP3

    async def _do_download():
        _, session_data = _require_session()
        token_manager, client = await _build_client(session_data)

        try:
            # Check subscription for WAV availability
            console.print("\n[dim]Checking subscription status...[/dim]")
            billing = await client.get_billing_info()

            tier_badge = {
                "free": "[white on red] FREE [/white on red]",
                "pro": "[white on blue] PRO [/white on blue]",
                "premier": "[black on yellow] PREMIER [/black on yellow]",
            }.get(billing.tier, f"[dim]{billing.tier}[/dim]")

            console.print(f"  Subscription: {tier_badge}")

            # Gray out WAV if not on pro/premier
            if config.download_wav and billing.tier == "free":
                console.print(
                    "[yellow]  ⚠️  WAV downloads require Pro or Premier subscription. "
                    "Skipping WAV format.[/yellow]"
                )
                config.download_wav = False

            # Build filter options
            from suno_downloaderist.api.models import FilterOptions
            filters = FilterOptions(
                date_from=since,
                date_to=until,
                liked_only=liked_only,
                min_plays=min_plays or 0,
                title_search=search or "",
            )

            # Fetch library with filters & smart cache
            console.print("\n[dim]Scanning your Suno library...[/dim]")
            with console.status("[bold purple]Syncing library songs..."):
                clips = await client.get_all_clips(filter_options=filters, refresh_cache=rescan)

            if not clips:
                console.print("[yellow]No songs found matching your filters.[/yellow]")
                return

            # Group by title for version detection
            groups = client.group_by_title(clips)

            # Pre-download summary
            total_clips = len(clips)
            total_groups = len(groups)

            summary = Table(title="📋 Download Summary", border_style="purple")
            summary.add_column("Setting", style="bold")
            summary.add_column("Value")
            summary.add_row("Songs", f"{total_clips} tracks in {total_groups} groups")
            summary.add_row("Formats", config.formats_description)
            summary.add_row("Output", str(config.output_dir))
            summary.add_row("Workers", str(config.workers))
            summary.add_row("Skip existing", "Yes" if config.skip_existing else "No")
            if since:
                summary.add_row("Since", since.strftime("%Y-%m-%d %H:%M"))
            if until:
                summary.add_row("Until", until.strftime("%Y-%m-%d %H:%M"))
            if liked_only:
                summary.add_row("Filter", "Liked songs only")
            if search:
                summary.add_row("Search", search)
            if min_plays:
                summary.add_row("Min plays", str(min_plays))
            console.print()
            console.print(summary)

            if dry_run:
                console.print("\n[bold yellow]DRY RUN[/bold yellow] — listing songs that would be downloaded:\n")
                for clip in clips[:50]:
                    liked = "❤️ " if clip.is_liked else "  "
                    console.print(
                        f"  {liked}[bold]{clip.title}[/bold] "
                        f"[dim]({format_duration(clip.duration)}, "
                        f"{clip.model_name}, "
                        f"{clip.created_at.strftime('%Y-%m-%d %H:%M')})[/dim]"
                    )
                if len(clips) > 50:
                    console.print(f"\n  [dim]...and {len(clips) - 50} more[/dim]")
                return

            # Confirmation prompt
            if not yes:
                console.print()
                if not click.confirm(f"Download {total_clips} songs?", default=True):
                    console.print("[yellow]Download cancelled.[/yellow]")
                    return

            # Execute downloads
            from suno_downloaderist.downloader.engine import DownloadEngine
            from suno_downloaderist.downloader.organizer import FileOrganizer
            from suno_downloaderist.downloader.metadata import MetadataWriter
            from suno_downloaderist.downloader.lyrics import LyricsWriter
            from suno_downloaderist.downloader.id3 import ID3Tagger
            from suno_downloaderist.downloader.audio import convert_wav_to_mp3

            organizer = FileOrganizer()
            metadata_writer = MetadataWriter()
            lyrics_writer = LyricsWriter()
            id3_tagger = ID3Tagger()
            engine = DownloadEngine(
                workers=config.workers,
                cdn_delay=config.cdn_delay,
                skip_existing=config.skip_existing,
                max_retries=config.max_retries,
            )

            console.print()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                "•",
                DownloadColumn(),
                "•",
                TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"[purple]Downloading ({config.workers} workers)...",
                    total=total_clips,
                )

                downloaded = 0
                skipped = 0
                failed = 0
                failures: list[tuple[str, str]] = []
                lock = asyncio.Lock()
                sem = asyncio.Semaphore(config.workers)

                async def _download_track(clip: Any, version_num: Optional[int]):
                    nonlocal downloaded, skipped, failed
                    async with sem:
                        try:
                            # 1. Organize paths
                            paths = organizer.organize_clip(
                                clip=clip,
                                base_dir=config.output_dir,
                                version_number=version_num,
                            )

                            # 2. Check if already downloaded
                            need_mp3 = config.download_mp3 and (not paths["mp3"].exists() or not config.skip_existing)
                            need_wav = config.download_wav and (not paths["wav"].exists() or not config.skip_existing)
                            need_mp4 = config.download_mp4 and clip.video_url and (not paths["mp4"].exists() or not config.skip_existing)

                            if not need_mp3 and not need_wav and not need_mp4:
                                async with lock:
                                    skipped += 1
                                    progress.update(task, advance=1)
                                return

                            # 3. Download cover art first (needed for ID3 tagging)
                            if config.include_cover_art and (not paths["cover"].exists() or not config.skip_existing):
                                from suno_downloaderist.api.endpoints import get_cdn_image_large_url
                                cover_url = clip.image_large_url or clip.image_url or get_cdn_image_large_url(clip.id)
                                if cover_url:
                                    await engine.download_file(
                                        url=cover_url,
                                        dest_path=paths["cover"],
                                    )

                            # 4. Handle Audio (WAV and/or MP3 via master audio stream)
                            if need_mp3 or need_wav:
                                wav_url = await client.get_wav_download_url(clip.id)
                                if not wav_url:
                                    async with lock:
                                        failures.append((clip.title, "Could not acquire WAV audio URL from Suno"))
                                        failed += 1
                                        progress.update(task, advance=1)
                                    return

                                wav_dest = paths["wav"] if config.download_wav else (paths["folder"] / f".temp_{clip.id}.wav")
                                wav_res = await engine.download_file(
                                    url=wav_url,
                                    dest_path=wav_dest,
                                )

                                if not wav_res.success:
                                    async with lock:
                                        failures.append((clip.title, wav_res.error_message or "WAV download failed"))
                                        failed += 1
                                        progress.update(task, advance=1)
                                    return

                                # Convert to 320kbps MP3 if requested
                                if config.download_mp3:
                                    mp3_ok = convert_wav_to_mp3(wav_dest, paths["mp3"], bitrate_kbps=320)
                                    if not mp3_ok:
                                        async with lock:
                                            failures.append((clip.title, "Failed to encode MP3 from master WAV"))
                                            failed += 1
                                            progress.update(task, advance=1)
                                        return

                                    # Embed ID3 tags & cover art
                                    if config.embed_id3_tags and paths["mp3"].exists():
                                        cover_path = paths["cover"] if paths["cover"].exists() else None
                                        id3_tagger.tag_mp3(
                                            file_path=paths["mp3"],
                                            clip=clip,
                                            cover_art_path=cover_path,
                                        )

                                # Cleanup temporary WAV if user only asked for MP3
                                if not config.download_wav and wav_dest.exists():
                                    try:
                                        wav_dest.unlink(missing_ok=True)
                                    except Exception:
                                        pass

                            # 5. Download video (MP4) if available
                            if need_mp4:
                                await engine.download_file(
                                    url=clip.video_url,
                                    dest_path=paths["mp4"],
                                )

                            # 6. Write metadata
                            metadata_writer.write_metadata_txt(clip, paths["txt"])
                            if config.include_json:
                                metadata_writer.write_metadata_json(clip, paths["json"])

                            # 7. Fetch and write synced lyrics
                            if config.include_synced_lyrics:
                                try:
                                    aligned = await client.get_aligned_lyrics(clip.id)
                                    if aligned:
                                        lyrics_writer.write_lrc(
                                            aligned_lyrics=aligned,
                                            title=clip.title,
                                            artist=clip.display_name or "Suno AI",
                                            dest_path=paths["lrc"],
                                        )
                                except Exception:
                                    logger.debug("Could not fetch synced lyrics for %s", clip.id)

                            async with lock:
                                downloaded += 1
                                progress.update(task, advance=1)

                        except Exception as exc:
                            async with lock:
                                failed += 1
                                failures.append((clip.title, str(exc)))
                                progress.update(task, advance=1)
                            logger.debug("Failed to download %s: %s", clip.title, exc)

                # Launch parallel worker tasks
                track_tasks = []
                for group_name, song_group in groups.items():
                    for version_idx, clip in enumerate(song_group.clips):
                        v_num = version_idx + 1 if len(song_group.clips) > 1 else None
                        track_tasks.append(_download_track(clip, v_num))

                await asyncio.gather(*track_tasks)

            # Final report
            console.print()
            report = Table(title="✅ Download Complete", border_style="green")
            report.add_column("Metric", style="bold")
            report.add_column("Count")
            report.add_row("Downloaded", f"[green]{downloaded}[/green]")
            report.add_row("Skipped (existing)", f"[yellow]{skipped}[/yellow]")
            report.add_row("Failed", f"[red]{failed}[/red]" if failed else "[green]0[/green]")
            report.add_row("Output folder", str(config.output_dir))
            console.print(report)

            if failures:
                console.print("\n[bold red]Failed downloads:[/bold red]")
                for title, error in failures[:20]:
                    console.print(f"  [red]✗[/red] {title}: {error}")
                if len(failures) > 20:
                    console.print(f"  [dim]...and {len(failures) - 20} more[/dim]")

        finally:
            await token_manager.stop_refresh_loop()

    try:
        asyncio.run(_do_download())
    except KeyboardInterrupt:
        console.print("\n[yellow]Download interrupted. Run again to resume (existing files will be skipped).[/yellow]")
    except click.ClickException:
        raise
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        logger.debug("Download error", exc_info=True)
        raise click.Abort()


# ─── LIST ───────────────────────────────────────────────────────────────────

@cli.command(name="list")
@click.option("--liked-only", is_flag=True, default=False, help="Only show liked songs.")
@click.option("--since", type=DATETIME_TYPE, default=None, help="Songs created after this date.")
@click.option("--until", type=DATETIME_TYPE, default=None, help="Songs created before this date.")
@click.option("--search", type=str, default=None, help="Filter by title.")
@click.option("--min-plays", type=int, default=None, help="Minimum play count.")
@click.option("--limit", type=int, default=None, help="Maximum number of songs to display.")
@click.option("--rescan", is_flag=True, default=False, help="Force a full library rescan instead of using cached index.")
def list_songs(
    liked_only: bool,
    since: datetime | None,
    until: datetime | None,
    search: str | None,
    min_plays: int | None,
    limit: int | None,
    rescan: bool,
) -> None:
    """List all songs in your Suno library.

    Shows a formatted table with song details. Use filters to narrow results.
    """
    async def _do_list():
        _, session_data = _require_session()
        token_manager, client = await _build_client(session_data)

        try:
            from suno_downloaderist.api.models import FilterOptions
            filters = FilterOptions(
                date_from=since,
                date_to=until,
                liked_only=liked_only,
                min_plays=min_plays or 0,
                title_search=search or "",
            )

            with console.status("[bold purple]Fetching your library..."):
                clips = await client.get_all_clips(filter_options=filters, refresh_cache=rescan)

            if not clips:
                console.print("[yellow]No songs found matching your filters.[/yellow]")
                return

            # Sort by creation date (newest first)
            clips.sort(key=lambda c: c.created_at, reverse=True)

            if limit:
                clips = clips[:limit]

            table = Table(title=f"🎵 Your Suno Library ({len(clips)} songs)", border_style="purple")
            table.add_column("#", style="dim", width=4)
            table.add_column("Title", style="bold", max_width=40)
            table.add_column("Duration", justify="right")
            table.add_column("Created", justify="right")
            table.add_column("Model", style="dim")
            table.add_column("❤️", justify="center", width=3)
            table.add_column("Plays", justify="right")

            for idx, clip in enumerate(clips, 1):
                liked = "❤️" if clip.is_liked else ""
                table.add_row(
                    str(idx),
                    clip.title or "[dim]Untitled[/dim]",
                    format_duration(clip.duration),
                    clip.created_at.strftime("%Y-%m-%d %H:%M"),
                    clip.model_name or "—",
                    liked,
                    str(clip.play_count),
                )

            console.print()
            console.print(table)
            console.print(f"\n[dim]Total: {len(clips)} songs[/dim]")

        finally:
            await token_manager.stop_refresh_loop()

    try:
        asyncio.run(_do_list())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
    except click.ClickException:
        raise
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        raise click.Abort()


# ─── INFO ───────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("clip_id")
def info(clip_id: str) -> None:
    """Show detailed information about a specific song.

    CLIP_ID is the Suno clip UUID (found in the song URL).
    """
    async def _do_info():
        _, session_data = _require_session()
        token_manager, client = await _build_client(session_data)

        try:
            with console.status("[bold purple]Fetching song info..."):
                clip = await client.get_clip_by_id(clip_id)

            if clip is None:
                console.print(f"[red]Song not found: {clip_id}[/red]")
                return

            panel_content = (
                f"[bold]{clip.title}[/bold]\n\n"
                f"Clip ID:     {clip.id}\n"
                f"Duration:    {format_duration(clip.duration)}\n"
                f"Created:     {clip.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"Model:       {clip.model_name} ({clip.major_model_version})\n"
                f"Status:      {clip.status}\n"
                f"Liked:       {'❤️ Yes' if clip.is_liked else 'No'}\n"
                f"Play count:  {clip.play_count}\n"
                f"Public:      {'Yes' if clip.is_public else 'No'}\n"
                f"Suno URL:    https://suno.com/song/{clip.id}\n"
            )

            if clip.metadata:
                panel_content += (
                    f"\n[bold]Style/Genre Prompt:[/bold]\n"
                    f"{clip.metadata.gpt_description_prompt or '(none)'}\n"
                    f"\n[bold]Tags:[/bold]\n"
                    f"{clip.metadata.tags or '(none)'}\n"
                )
                if clip.metadata.prompt:
                    # Truncate lyrics for display
                    lyrics_preview = clip.metadata.prompt[:500]
                    if len(clip.metadata.prompt) > 500:
                        lyrics_preview += "\n..."
                    panel_content += f"\n[bold]Lyrics:[/bold]\n{lyrics_preview}\n"

                if clip.metadata.continue_clip_id:
                    panel_content += f"\nExtended from: {clip.metadata.continue_clip_id}\n"
                if clip.metadata.concat_history:
                    panel_content += f"Concat history: {clip.metadata.concat_history}\n"

            console.print()
            console.print(Panel(panel_content, title="🎵 Song Details", border_style="purple"))

        finally:
            await token_manager.stop_refresh_loop()

    try:
        asyncio.run(_do_info())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
    except click.ClickException:
        raise
    except Exception as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        raise click.Abort()


# ─── DASHBOARD ──────────────────────────────────────────────────────────────

@cli.command()
@click.option("--port", "-p", type=int, default=None, help="Dashboard port (default: 8484).")
@click.option("--no-browser", is_flag=True, default=False, help="Don't auto-open browser.")
@click.pass_context
def dashboard(ctx: click.Context, port: int | None, no_browser: bool) -> None:
    """Launch the web dashboard for visual download management.

    Opens a local web interface in your browser for managing downloads
    with a visual progress display and configuration panel.
    """
    config: AppConfig = ctx.obj["config"]
    if port is not None:
        config.dashboard_port = port

    console.print(
        Panel(
            f"[bold]Suno Song Downloaderist Dashboard[/bold]\n\n"
            f"Starting on [link=http://localhost:{config.dashboard_port}]"
            f"http://localhost:{config.dashboard_port}[/link]\n"
            f"Press [bold]Ctrl+C[/bold] to stop.",
            title="🖥️  Dashboard",
            border_style="purple",
        )
    )

    try:
        from suno_downloaderist.dashboard.server import run_dashboard

        if not no_browser:
            import threading
            threading.Timer(
                1.5,
                lambda: webbrowser.open(f"http://localhost:{config.dashboard_port}"),
            ).start()

        run_dashboard(config)

    except KeyboardInterrupt:
        console.print("\n[green]Dashboard stopped.[/green]")
    except ImportError as exc:
        console.print(f"[red]Dashboard dependencies missing: {exc}[/red]")
        console.print("[dim]Install with: pip install 'suno-song-downloaderist[dev]'[/dim]")


# ─── CONFIG ─────────────────────────────────────────────────────────────────

@cli.group()
def config() -> None:
    """View or modify configuration settings."""
    pass


@config.command(name="show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Display current configuration."""
    cfg: AppConfig = ctx.obj["config"]

    table = Table(title="⚙️  Configuration", border_style="purple")
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    table.add_column("Description", style="dim")

    for field_name, field_info in cfg.model_fields.items():
        value = getattr(cfg, field_name)
        desc = field_info.description or ""
        table.add_row(field_name, str(value), desc)

    console.print()
    console.print(table)
    console.print(f"\n[dim]Config file: {load_config.__module__}[/dim]")


@config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """Set a configuration value.

    Example: suno-dl config set output_dir ~/Desktop/MySunoSongs
    """
    cfg: AppConfig = ctx.obj["config"]

    if key not in cfg.model_fields:
        valid_keys = ", ".join(cfg.model_fields.keys())
        raise click.ClickException(
            f"Unknown config key: '{key}'. Valid keys: {valid_keys}"
        )

    # Parse value based on field type
    field_info = cfg.model_fields[key]
    field_type = field_info.annotation

    try:
        if field_type is bool:
            parsed = value.lower() in ("true", "1", "yes", "on")
        elif field_type is int:
            parsed = int(value)
        elif field_type is float:
            parsed = float(value)
        elif field_type is Path:
            parsed = Path(value).expanduser()
        else:
            parsed = value

        setattr(cfg, key, parsed)
        save_config(cfg)
        console.print(f"[green]✅ Set {key} = {parsed}[/green]")

    except (ValueError, TypeError) as exc:
        raise click.ClickException(f"Invalid value for {key}: {exc}")


@config.command(name="reset")
def config_reset() -> None:
    """Reset all settings to defaults."""
    if click.confirm("Reset all configuration to defaults?"):
        reset_config()
        console.print("[green]✅ Configuration reset to defaults.[/green]")


# ─── Entry Point ────────────────────────────────────────────────────────────

def main() -> None:
    """Main entry point for the CLI."""
    cli(auto_envvar_prefix="SUNO")


if __name__ == "__main__":
    main()

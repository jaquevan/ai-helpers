#!/usr/bin/env python3
"""
Visual Page Data Extractor

Extracts DOM structure and screenshots from running pages using Playwright.
Alternatively, can analyze existing screenshots without DOM extraction.
Output is consumed by Claude Code for AI-powered design guideline analysis.

Usage:
  python3 visual_analyze.py <url> [--output-dir=<path>]
  python3 visual_analyze.py --screenshot=<path> [--output-dir=<path>]
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict

def extract_page_data(
    url: str,
    page_load_timeout: int = 30000,
    capture_screenshot: bool = True,
) -> Dict:
    """Extract data from the page using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "URL extraction requires Playwright. Install requirements-visual.txt "
            "and a Chromium browser, or use --screenshot."
        ) from exc
    print("Launching browser...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1920, "height": 1080})

        try:
            print(f"Loading {url}...")
            page.goto(url, wait_until='load', timeout=page_load_timeout)
            page.wait_for_timeout(2000)  # Wait for JS to execute

            screenshot_bytes = None
            if capture_screenshot:
                print("Capturing screenshot...")
                screenshot_bytes = page.screenshot(full_page=True, type='png')

            # Extract page structure with bounding boxes
            print("Extracting DOM elements with positions...")
            page_data = page.evaluate("""
                () => {
                    const getBoundingBox = (el) => {
                        const rect = el.getBoundingClientRect();
                        return {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            centerX: Math.round(rect.x + rect.width / 2),
                            centerY: Math.round(rect.y + rect.height / 2)
                        };
                    };

                    return {
                        title: document.title,
                        url: window.location.href,
                        navigation: Array.from(document.querySelectorAll('nav, [role="navigation"]')).map((nav, idx) => ({
                            id: `nav-${idx}`,
                            bbox: getBoundingBox(nav),
                            items: Array.from(nav.querySelectorAll('a, button')).map((item, itemIdx) => ({
                                id: `nav-${idx}-item-${itemIdx}`,
                                text: item.textContent.trim(),
                                tag: item.tagName,
                                href: item.href || null,
                                ariaLabel: item.getAttribute('aria-label'),
                                classes: item.className,
                                bbox: getBoundingBox(item)
                            }))
                        })),
                        headers: Array.from(document.querySelectorAll('h1, h2, h3, h4')).map((h, idx) => ({
                            id: `header-${idx}`,
                            level: h.tagName,
                            text: h.textContent.trim(),
                            classes: h.className,
                            bbox: getBoundingBox(h)
                        })),
                        buttons: Array.from(document.querySelectorAll('button, [role="button"]')).map((btn, idx) => ({
                            id: `button-${idx}`,
                            text: btn.textContent.trim(),
                            type: btn.type || btn.getAttribute('type'),
                            classes: btn.className,
                            ariaLabel: btn.getAttribute('aria-label'),
                            icon: btn.querySelector('svg') ? 'has-icon' : null,
                            bbox: getBoundingBox(btn)
                        })),
                        tables: Array.from(document.querySelectorAll('table')).map((table, idx) => ({
                            id: `table-${idx}`,
                            headers: Array.from(table.querySelectorAll('th')).map(th => th.textContent.trim()),
                            rowCount: table.querySelectorAll('tbody tr').length,
                            hasPagination: !!table.closest('.pf-c-table-wrapper, .pf-c-pagination'),
                            bbox: getBoundingBox(table)
                        })),
                        icons: Array.from(document.querySelectorAll('svg')).map((svg, idx) => ({
                            id: `icon-${idx}`,
                            ariaLabel: svg.getAttribute('aria-label'),
                            classes: svg.className.baseVal || svg.className,
                            parent: svg.parentElement.tagName,
                            bbox: getBoundingBox(svg)
                        }))
                    };
                }
            """)

            page_data['screenshot_bytes'] = screenshot_bytes

            browser.close()
            print("Page data extracted successfully")
            return page_data

        except Exception as e:
            browser.close()
            raise Exception(f"Failed to extract page data: {e}")




def load_screenshot_data(screenshot_path: str) -> Dict:
    """Load existing screenshot for analysis (no DOM extraction)."""
    print(f"Loading screenshot from {screenshot_path}...")

    screenshot_file = Path(screenshot_path)
    if not screenshot_file.exists():
        raise FileNotFoundError(f"Screenshot not found: {screenshot_path}")

    with open(screenshot_file, 'rb') as f:
        screenshot_bytes = f.read()

    # Create minimal page data (no DOM structure available from static image)
    page_data = {
        'screenshot_bytes': screenshot_bytes,
        'url': f'file://{screenshot_file.absolute()}',
        'title': screenshot_file.stem,
        'navigation': [],
        'headers': [],
        'buttons': [],
        'tables': [],
        'icons': [],
        'mode': 'screenshot-only'
    }

    print("Screenshot loaded successfully")
    print("Note: DOM structure not available in screenshot-only mode")
    return page_data


def main():
    parser = argparse.ArgumentParser(description='Visual Page Data Extractor')
    parser.add_argument('url', nargs='?', help='URL of the page to extract (e.g., http://localhost:9000/projects)')
    parser.add_argument('--screenshot', help='Path to existing screenshot to analyze (skips browser extraction)')
    parser.add_argument('--output-dir', default='visual-extraction',
                        help='Output directory for extracted data (default: visual-extraction)')
    parser.add_argument('--page-load-timeout', type=int, default=30000,
                        help='Page load timeout in milliseconds (default: 30000)')
    parser.add_argument('--dom-only', action='store_true',
                        help='Extract DOM data without capturing a duplicate screenshot')
    args = parser.parse_args()

    print("Visual Page Data Extractor\n")

    # Validate arguments
    if not args.screenshot and not args.url:
        parser.error("Either URL or --screenshot must be provided")
    if args.screenshot and args.url:
        parser.error("Cannot specify both URL and --screenshot")
    if args.screenshot and args.dom_only:
        parser.error("--dom-only requires a URL")

    # Extract or load page data
    try:
        if args.screenshot:
            page_data = load_screenshot_data(args.screenshot)
        else:
            page_data = extract_page_data(
                args.url,
                args.page_load_timeout,
                capture_screenshot=not args.dom_only,
            )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # Save screenshot
    screenshot_path = None
    if page_data.get('screenshot_bytes') is not None:
        screenshot_path = output_dir / f"screenshot_{timestamp}.png"
        with open(screenshot_path, 'wb') as f:
            f.write(page_data['screenshot_bytes'])
        print(f"\nScreenshot saved: {screenshot_path}")

    # Save structured data (without screenshot bytes)
    data_to_save = {
        'url': page_data.get('url'),
        'title': page_data.get('title'),
        'navigation': page_data.get('navigation', []),
        'headers': page_data.get('headers', []),
        'buttons': page_data.get('buttons', []),
        'tables': page_data.get('tables', []),
        'icons': page_data.get('icons', []),
        'extracted_at': timestamp
    }

    data_path = output_dir / f"page_data_{timestamp}.json"
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=2)
    print(f"Page data saved: {data_path}")

    # Print summary
    if page_data.get('mode') == 'screenshot-only':
        print(f"\nMode: Screenshot-only analysis (no DOM extraction)")
    else:
        print(f"\nExtracted:")
        print(f"  • {len(data_to_save.get('buttons', []))} buttons")
        print(f"  • {len(data_to_save.get('headers', []))} headers")
        print(f"  • {len(data_to_save.get('navigation', []))} navigation sections")
        print(f"  • {len(data_to_save.get('tables', []))} tables")
        print(f"  • {len(data_to_save.get('icons', []))} icons")

    # Output paths for Claude Code to consume
    if screenshot_path:
        print(f"\nOUTPUT_SCREENSHOT={screenshot_path}")
    print(f"OUTPUT_DATA={data_path}")


if __name__ == '__main__':
    main()

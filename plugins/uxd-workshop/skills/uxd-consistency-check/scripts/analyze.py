#!/usr/bin/env python3
"""
Design Guidelines Checker

Scans all design guidelines and runs automated checks to find violations.

Usage:
  python3 analyze.py [--src=<path>] [--category=<cat>] [--guideline=<id>] [--verbose]
  python3 analyze.py --src=<path> --changed --base-ref=main [--verbose]
"""

import os
import sys
import re
import json
import subprocess
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ANSI color codes
class Colors:
    RESET = '\033[0m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    CYAN = '\033[36m'
    GRAY = '\033[90m'
    BOLD = '\033[1m'

BASE_URL = 'http://localhost:4010'

# Route mappings for PROTOTYPE codebase (src/app/ structure)
FILE_TO_ROUTE_PROTOTYPE = {
    'src/app/Settings/Policies': '/settings/policies',
    'src/app/Settings/APIKeys': '/gen-ai-studio/api-keys',
    'src/app/Settings/Subscriptions': '/settings/subscriptions',
    'src/app/Settings/MCPResources': '/settings/mcp-resources/settings',
    'src/app/Settings/ClusterSettings': '/settings/cluster/general',
    'src/app/Settings/EnvironmentSetup/WorkbenchImages': '/settings/environment/workbench-images',
    'src/app/Settings/EnvironmentSetup/HardwareProfiles': '/settings/environment/hardware-profiles',
    'src/app/Settings/EnvironmentSetup/ConnectionTypes': '/settings/environment/connection-types',
    'src/app/Settings/ModelResources/ServingRuntimes': '/settings/model-resources/serving-runtimes',
    'src/app/Settings/ModelResources/ModelRegistrySettings': '/settings/model-resources/registry-settings',
    'src/app/Settings/ModelResources/ModelCatalogSettings': '/settings/model-resources/model-catalog-settings',
    'src/app/Settings/UserManagement': '/settings/user-management',
    'src/app/Projects/screens/detail': '/projects',
    'src/app/Projects': '/projects',
    'src/app/Connections': '/connections',
    'src/app/AIHub/Models/ModelCatalog': '/ai-hub/models/catalog',
    'src/app/AIHub/Models/ModelRegistry': '/ai-hub/models/registry',
    'src/app/AIHub/Models': '/ai-hub/models/catalog',
    'src/app/AIHub/Deployments': '/ai-hub/models/deployments',
    'src/app/AIHub/MCPServers': '/ai-hub/mcp/catalog',
    'src/app/AIHub/MVPServers': '/ai-assets/mvp-servers',
    'src/app/AIHub/Guardrails': '/ai-assets/guardrails',
    'src/app/GenAIStudio/AssetEndpoints': '/gen-ai-studio/asset-endpoints',
    'src/app/GenAIStudio/Playground': '/gen-ai-studio/playground',
    'src/app/GenAIStudio/ModelPlayground': '/gen-ai-studio/model-playground',
    'src/app/GenAIStudio/MyAgents': '/gen-ai-studio/my-agents',
    'src/app/GenAIStudio/PromptEngineering': '/gen-ai-studio/prompt-engineering',
    'src/app/GenAIStudio/KnowledgeSources': '/gen-ai-studio/knowledge-sources',
    'src/app/GenAIStudio/AutoRAG': '/gen-ai-studio/autorag',
    'src/app/GenAIStudio/PromptLab': '/gen-ai-studio/prompt-lab',
    'src/app/DevelopTrain/Workbenches': '/develop-train/workbenches',
    'src/app/DevelopTrain/FeatureStore/Overview': '/develop-train/feature-store/overview',
    'src/app/DevelopTrain/FeatureStore/Entities': '/develop-train/feature-store/entities',
    'src/app/DevelopTrain/FeatureStore/DataSources': '/develop-train/feature-store/data-sources',
    'src/app/DevelopTrain/FeatureStore/DataSets': '/develop-train/feature-store/data-sets',
    'src/app/DevelopTrain/FeatureStore/Features': '/develop-train/feature-store/features',
    'src/app/DevelopTrain/FeatureStore/FeatureViews': '/develop-train/feature-store/feature-views',
    'src/app/DevelopTrain/FeatureStore/FeatureServices': '/develop-train/feature-store/feature-services',
    'src/app/DevelopTrain/Pipelines/PipelineDefinitions': '/develop-train/pipelines/definitions',
    'src/app/DevelopTrain/Pipelines/Runs': '/develop-train/pipelines/runs',
    'src/app/DevelopTrain/Pipelines/Artifacts': '/develop-train/pipelines/artifacts',
    'src/app/DevelopTrain/Pipelines/Executions': '/develop-train/pipelines/executions',
    'src/app/DevelopTrain/Evaluations': '/develop-train/evaluations',
    'src/app/DevelopTrain/Experiments': '/develop-train/experiments',
    'src/app/DevelopTrain/Pipelines': '/develop-train/pipelines/definitions',
    'src/app/ObserveMonitor/Dashboard': '/observe-monitor/dashboard',
    'src/app/ObserveMonitor/WorkloadMetrics': '/observe-monitor/workload-metrics',
    'src/app/ObserveMonitor/TrainingJobs': '/develop-train/training-jobs',
    'src/app/LearningResources': '/learning-resources',
    'src/app/Applications/Enabled': '/applications/enabled',
    'src/app/Applications/Explore': '/applications/explore',
    'src/app/FeatureFlags': '/feature-flags',
    'src/app/AppLayout': '/',
    'src/app/Home': '/',
}

# Route mappings for ODH-DASHBOARD (pages/, concepts/, components/ structure)
FILE_TO_ROUTE_ODH_DASHBOARD = {
    # Settings pages
    'src/pages/modelRegistrySettings': '/modelRegistrySettings',
    'src/pages/notebookController': '/notebookController',
    'src/pages/groupSettings': '/groupSettings',
    'src/pages/acceleratorProfiles': '/acceleratorProfiles',
    'src/pages/storageClasses': '/storageClasses',
    'src/pages/clusterSettings': '/clusterSettings',

    # Main pages
    'src/pages/projects': '/projects',
    'src/pages/modelServing': '/modelServing',
    'src/pages/pipelines': '/pipelines',
    'src/pages/distributedWorkloads': '/distributedWorkloads',
    'src/pages/learningCenter': '/resources',
    'src/pages/ApplicationsPage.tsx': '/explore',
    'src/pages/exploreApplication': '/explore/application',
    'src/pages/connectionTypes': '/connectionTypes',
    'src/pages/BYONImages': '/notebookImages',

    # Concepts (reusable page sections) - map to likely parent pages
    'src/concepts/hardwareProfiles': '/notebookController',  # Hardware profiles in settings
    'src/concepts/pipelines': '/pipelines',
    'src/concepts/projects': '/projects',
    'src/concepts/modelServing': '/modelServing',
    'src/concepts/k8s': '/',  # K8s utilities, visible everywhere

    # App-level (header, layout) - visible on all pages
    'src/app': '/',

    # Components (shared) - no specific route, visible on multiple pages
    # Omit these from mapping as they appear everywhere
}

# Active route mapping (auto-detected based on file structure)
_active_route_mapping = None

def detect_route_mapping(project_root: str) -> Dict[str, str]:
    """Auto-detect which route mapping to use based on project structure."""
    global _active_route_mapping

    if _active_route_mapping is not None:
        return _active_route_mapping

    project_path = Path(project_root)
    src_path = project_path / 'src'

    # Check for ODH-Dashboard structure (pages/ + concepts/ directories)
    if (src_path / 'pages').exists() and (src_path / 'concepts').exists():
        _active_route_mapping = FILE_TO_ROUTE_ODH_DASHBOARD
        return FILE_TO_ROUTE_ODH_DASHBOARD

    # Check for prototype structure (app/ directory with capitalized subdirs)
    app_path = src_path / 'app'
    if app_path.exists():
        subdirs = [d.name for d in app_path.iterdir() if d.is_dir()]
        # Prototype has PascalCase dirs like Settings, Projects, AIHub
        if any(d[0].isupper() for d in subdirs):
            _active_route_mapping = FILE_TO_ROUTE_PROTOTYPE
            return FILE_TO_ROUTE_PROTOTYPE

    # Default to prototype mapping
    _active_route_mapping = FILE_TO_ROUTE_PROTOTYPE
    return FILE_TO_ROUTE_PROTOTYPE

def get_route_for_file(file_path: str, project_root: str = None) -> Optional[str]:
    """Find the longest matching route prefix for a given file path."""
    # Determine which mapping to use
    if project_root:
        route_map = detect_route_mapping(project_root)
    else:
        route_map = _active_route_mapping or FILE_TO_ROUTE_PROTOTYPE

    best_match = None
    best_length = 0
    for prefix, route in route_map.items():
        if file_path.startswith(prefix) and len(prefix) > best_length:
            best_match = route
            best_length = len(prefix)
    return f"{BASE_URL}{best_match}" if best_match else None

def parse_frontmatter(content: str) -> Optional[Dict]:
    """Parse YAML frontmatter from markdown content."""
    match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return None

    frontmatter = {}
    for line in match.group(1).split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # Parse arrays
            if value.startswith('[') and value.endswith(']'):
                frontmatter[key] = [v.strip() for v in value[1:-1].split(',')]
            elif value == 'true':
                frontmatter[key] = True
            elif value == 'false':
                frontmatter[key] = False
            else:
                frontmatter[key] = value

    return frontmatter

def extract_rule_text(content: str) -> Optional[str]:
    """Extract the first paragraph of the ## Rule section."""
    match = re.search(r'## Rule\n\n(.*?)(?=\n## |\n###|\Z)', content, re.DOTALL)
    if not match:
        return None

    first_para = match.group(1).strip().split('\n\n')[0]
    # Strip markdown bold, backticks, and list bullets
    text = re.sub(r'\*\*', '', first_para)
    text = re.sub(r'`', '', text)
    text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n', ' ', text)
    return text.strip()

def extract_check_commands(content: str) -> List[Dict[str, str]]:
    """Extract bash commands from the Automated Checks section.

    Distinguishes between violation-finding commands and exception commands.
    Exception commands (from **Exception** sections) are marked with is_exception=True.
    """
    commands = []

    # Find the Automated Checks section
    match = re.search(r'## Automated Checks\n\n(.*?)(?=\n## |\Z)', content, re.DOTALL)
    if not match:
        return commands

    checks_section = match.group(1)

    # Split the checks section to identify exception subsections
    # Look for **Exception patterns to identify exception blocks
    exception_pattern = r'\*\*Exception[s]?\s*\([^)]+\):\*\*'

    # Track position of exception markers
    exception_positions = []
    for exception_match in re.finditer(exception_pattern, checks_section):
        exception_positions.append(exception_match.start())

    # Extract bash code blocks with their positions
    code_blocks = list(re.finditer(r'```bash\n(.*?)```', checks_section, re.DOTALL))

    for block_match in code_blocks:
        code_block = block_match.group(1)
        block_start = block_match.start()

        # Determine if this code block is in an exception section
        # It's an exception if there's an exception marker before it and no other code block between them
        is_exception = False
        for exc_pos in exception_positions:
            if exc_pos < block_start:
                # Check if any other code block is between the exception marker and this block
                other_blocks_between = any(
                    exc_pos < other.start() < block_start
                    for other in code_blocks if other != block_match
                )
                if not other_blocks_between:
                    is_exception = True
                    break

        lines = [line.strip() for line in code_block.split('\n') if line.strip()]

        pending_description = None
        for line in lines:
            if line.startswith('#'):
                # Accumulate comment lines as description
                comment = line[1:].strip()
                pending_description = f"{pending_description} {comment}" if pending_description else comment
            else:
                commands.append({
                    'command': line,
                    'description': pending_description,
                    'is_exception': is_exception
                })
                pending_description = None

    return commands

def get_changed_files(base_ref: str, cwd: str, verbose: bool) -> Optional[set]:
    """Get list of changed files compared to base ref.

    Returns a set of relative file paths that have changed compared to base_ref.
    Returns None if not in a git repository or if git command fails.
    """
    try:
        # First check if we're in a git repository
        check_result = subprocess.run(
            ['git', 'rev-parse', '--git-dir'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5
        )

        if check_result.returncode != 0:
            if verbose:
                print(f"{Colors.YELLOW}Not in a git repository, cannot use --changed mode{Colors.RESET}")
            return None

        # Get changed files (both staged and unstaged)
        result = subprocess.run(
            ['git', 'diff', '--name-only', base_ref],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            if verbose:
                print(f"{Colors.YELLOW}Warning: git diff failed: {result.stderr.strip()}{Colors.RESET}")
            return None

        changed_files = set(line.strip() for line in result.stdout.split('\n') if line.strip())

        untracked = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if untracked.returncode == 0:
            changed_files.update(
                line.strip() for line in untracked.stdout.splitlines() if line.strip()
            )

        if verbose and changed_files:
            print(f"{Colors.CYAN}Found {len(changed_files)} changed file(s) compared to {base_ref}{Colors.RESET}")

        return changed_files

    except Exception as e:
        if verbose:
            print(f"{Colors.YELLOW}Error getting changed files: {e}{Colors.RESET}")
        return None


def get_changed_lines(base_ref: str, cwd: str, verbose: bool) -> Optional[Dict[str, Set[int]]]:
    """Return added/modified line numbers by file for a zero-context Git diff."""
    try:
        result = subprocess.run(
            ['git', 'diff', '--unified=0', '--no-color', base_ref, '--'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            if verbose:
                print(f"{Colors.YELLOW}Warning: git diff failed: {result.stderr.strip()}{Colors.RESET}")
            return None

        changed_lines: Dict[str, Set[int]] = {}
        current_file = None
        for line in result.stdout.splitlines():
            if line.startswith('+++ '):
                current_file = line[4:].strip()
                if current_file == '/dev/null':
                    current_file = None
                    continue
                if current_file.startswith('b/'):
                    current_file = current_file[2:]
                changed_lines.setdefault(current_file, set())
                continue

            if current_file and line.startswith('@@ '):
                match = re.search(r'\+(\d+)(?:,(\d+))?', line)
                if not match:
                    continue
                start = int(match.group(1))
                count = int(match.group(2) or '1')
                changed_lines[current_file].update(range(start, start + count))

        untracked = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if untracked.returncode == 0:
            for relative_path in untracked.stdout.splitlines():
                source_path = Path(cwd) / relative_path
                if not source_path.is_file():
                    continue
                line_count = len(source_path.read_text(errors='ignore').splitlines())
                changed_lines[relative_path] = set(range(1, line_count + 1))

        return changed_lines
    except Exception as e:
        if verbose:
            print(f"{Colors.YELLOW}Error getting changed lines: {e}{Colors.RESET}")
        return None


def _changed_line_match(line: str, changed_lines: Dict[str, Set[int]]) -> bool:
    """Whether grep-like output points to an added or modified line."""
    colon_match = re.match(r'^(.+?):(\d+):', line)
    dash_match = re.match(r'^(.+?)-(\d+)-', line)
    match = colon_match or dash_match
    file_path = match.group(1) if match else line.split(':', 1)[0]
    normalized = file_path.removeprefix('./')

    matching_path = next((
        path for path in changed_lines
        if normalized == path or normalized.endswith('/' + path) or path.endswith('/' + normalized)
    ), None)
    if matching_path is None:
        return False
    if not match:
        return True
    return int(match.group(2)) in changed_lines[matching_path]


CATEGORY_MARKERS = {
    'foundations': re.compile(r'<style\b|\bstyle\s*=|\bstyle\s*=\s*\{\{|\.s?css\b|rel=["\']stylesheet["\']'),
    'buttons': re.compile(r'\bButton\b|variant=["\'](?:primary|secondary|tertiary)["\']'),
    'icons': re.compile(r'\b[A-Z][A-Za-z0-9]*Icon\b|@patternfly/react-icons'),
    'labels': re.compile(r'\b(?:Label|Badge)\b'),
    'layouts': re.compile(r'\b(?:Page|PageSection|Stack|Split|Flex|Card|EmptyState|Toolbar)\b'),
    'menus': re.compile(r'\b(?:Menu|MenuToggle|Dropdown|Select)\b'),
    'navigation': re.compile(r'\b(?:Nav|NavItem|NavExpandable|Sidebar)\b|pf-v\d+-c-nav'),
    'tables': re.compile(r'\b(?:Table|Tr|Td|Th|Thead|Tbody|Pagination)\b'),
}


def detect_applicable_categories(changed_files: set, cwd: str) -> Optional[set]:
    """Select guideline categories from changed source without an LLM pre-pass."""
    content = []
    for relative_path in changed_files:
        path = Path(cwd) / relative_path
        if not path.is_file() or path.suffix.lower() not in {
            '.css', '.htm', '.html', '.js', '.jsx', '.scss', '.ts', '.tsx'
        }:
            continue
        content.append(path.read_text(errors='ignore'))
    if not content:
        return None
    joined = '\n'.join(content)
    matched = {
        category for category, marker in CATEGORY_MARKERS.items()
        if marker.search(joined)
    }
    if not matched:
        return None
    matched.add('foundations')
    return matched


def run_check_command(
    command: str,
    cwd: str,
    verbose: bool,
    changed_files: Optional[set] = None,
    changed_lines: Optional[Dict[str, Set[int]]] = None,
) -> Optional[List[str]]:
    """Run a check command and optionally filter findings to changed lines."""
    try:
        if not (Path(cwd) / 'src').is_dir():
            command = re.sub(r'(?<![\w.-])src(?=/|\s|$)', '.', command)
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30
        )

        # If there's output, it might be violations
        if result.stdout:
            lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

            # Filter to only changed files if specified
            if changed_lines is not None:
                lines = [line for line in lines if _changed_line_match(line, changed_lines)]
            elif changed_files:
                filtered_lines = []
                for line in lines:
                    # Extract file path from grep output (format: file:line:content or file:content)
                    if ':' in line:
                        file_path = line.split(':', 1)[0]
                        # Check if this file is in the changed files set
                        if any(file_path.endswith(changed_file) or changed_file in file_path
                               for changed_file in changed_files):
                            filtered_lines.append(line)
                    elif any(changed_file in line for changed_file in changed_files):
                        # Line might be just a filename
                        filtered_lines.append(line)

                lines = filtered_lines

            return lines if lines else None

        return None

    except subprocess.CalledProcessError as e:
        # grep returns exit code 1 when no matches found (success for us)
        if e.returncode == 1 and not e.stdout:
            return None

        if verbose:
            print(f"{Colors.YELLOW}Warning: Command failed: {command}{Colors.RESET}")
            print(f"{Colors.GRAY}{str(e)}{Colors.RESET}")
        return None
    except Exception as e:
        if verbose:
            print(f"{Colors.YELLOW}Warning: Command error: {command}{Colors.RESET}")
            print(f"{Colors.GRAY}{str(e)}{Colors.RESET}")
        return None

def is_file_path(s: str) -> bool:
    """Check if string looks like a file path."""
    return '/' in s or re.search(r'\.(tsx?|jsx?)$', s) is not None

def parse_matches_to_by_file(matches: List[str]) -> Dict[str, List[Dict]]:
    """Parse grep output lines into a {file: [{line, content}]} map."""
    by_file = {}

    for match in matches:
        if match == '--':
            continue

        trimmed = match.strip()
        if not trimmed:
            continue

        # Parse grep context lines first. Their content can contain colons (common
        # in JSX object props), which would otherwise be mistaken for separators.
        dash_match = re.match(r'^(.+?)-([0-9]+)-(.*)$', trimmed)
        if dash_match:
            file, line, content = dash_match.groups()
            if file not in by_file:
                by_file[file] = []
            by_file[file].append({'line': line, 'content': content.strip()})
            continue

        # Try file:line:content format
        if ':' in trimmed:
            parts = trimmed.split(':', 2)
            if len(parts) >= 2:
                file = parts[0]
                # Check if second part is a line number
                if len(parts) == 3 and parts[1].isdigit():
                    if file not in by_file:
                        by_file[file] = []
                    by_file[file].append({'line': parts[1], 'content': parts[2].strip()})
                    continue
                elif is_file_path(file):
                    if file not in by_file:
                        by_file[file] = []
                    by_file[file].append({'line': None, 'content': parts[1].strip()})
                    continue

        # Just a file path
        if is_file_path(trimmed):
            if trimmed not in by_file:
                by_file[trimmed] = []
            by_file[trimmed].append({'line': None, 'content': '(contains violation)'})
            continue

        # Other output
        if '(output)' not in by_file:
            by_file['(output)'] = []
        by_file['(output)'].append({'line': None, 'content': trimmed})

    return by_file

def print_file_group(by_file: Dict, project_root: str):
    """Print violations grouped by file."""
    MAX_FILES = 10
    MAX_LINES_PER_FILE = 3

    file_entries = list(by_file.items())

    for file, lines in file_entries[:MAX_FILES]:
        abs_file = os.path.join(project_root, file)
        rel_file = os.path.relpath(abs_file, project_root)
        file_count = len(lines)
        ui_url = get_route_for_file(rel_file, project_root)
        url_suffix = f"  {Colors.CYAN}{ui_url}{Colors.RESET}" if ui_url else ""

        print(f"\n    {Colors.BOLD}{rel_file}{Colors.RESET} {Colors.GRAY}({file_count} violation{'s' if file_count > 1 else ''}){Colors.RESET}{url_suffix}")

        for i, item in enumerate(lines[:MAX_LINES_PER_FILE]):
            line_num = item['line']
            content = item['content']

            if line_num:
                loc = f"{Colors.BLUE}{rel_file}:{line_num}{Colors.RESET}"
            else:
                loc = f"{Colors.BLUE}{rel_file}{Colors.RESET}"

            snippet = content[:97] + '…' if len(content) > 100 else content
            print(f"      {loc}  {Colors.GRAY}{snippet}{Colors.RESET}")

        if len(lines) > MAX_LINES_PER_FILE:
            print(f"      {Colors.GRAY}… and {len(lines) - MAX_LINES_PER_FILE} more in this file{Colors.RESET}")

    if len(file_entries) > MAX_FILES:
        print(f"\n    {Colors.GRAY}… and {len(file_entries) - MAX_FILES} more files{Colors.RESET}")

def check_guideline(
    category: str,
    filename: str,
    project_root: str,
    verbose: bool,
    changed_files: Optional[set] = None,
    changed_lines: Optional[Dict[str, Set[int]]] = None,
) -> Optional[Dict]:
    """Check a single guideline file, optionally filtered to changed files."""
    guidelines_dir = Path(__file__).parent.parent / 'guidelines'
    filepath = guidelines_dir / category / filename

    try:
        content = filepath.read_text(encoding='utf-8')
    except Exception as e:
        if verbose:
            print(f"{Colors.GRAY}Error reading {filename}: {e}{Colors.RESET}")
        return None

    frontmatter = parse_frontmatter(content)
    if not frontmatter:
        if verbose:
            print(f"{Colors.GRAY}Skipping {filename}: No frontmatter{Colors.RESET}")
        return None

    if not frontmatter.get('automatable'):
        if verbose:
            print(f"{Colors.GRAY}Skipping {frontmatter.get('title', filename)}: Not automatable{Colors.RESET}")
        return None

    commands = extract_check_commands(content)
    if not commands:
        if verbose:
            print(f"{Colors.YELLOW}Warning: {frontmatter.get('title', filename)} is marked automatable but has no check commands{Colors.RESET}")
        return None

    # Separate exception commands from violation commands
    exception_commands = [cmd for cmd in commands if cmd.get('is_exception')]
    violation_commands = [cmd for cmd in commands if not cmd.get('is_exception')]

    # First, run exception commands to collect valid patterns to exclude
    exception_matches = set()
    for cmd_info in exception_commands:
        command = cmd_info['command']
        if verbose:
            print(f"{Colors.GRAY}Running exception check: {command}{Colors.RESET}")

        result = run_check_command(
            command, project_root, verbose, changed_files, changed_lines
        )
        if result:
            # Store file:line combinations from exceptions
            for match in result:
                # Parse the match to extract file and line
                if ':' in match:
                    parts = match.split(':', 2)
                    if len(parts) >= 2:
                        file = parts[0]
                        # For file:line:content format
                        if len(parts) == 3 and parts[1].isdigit():
                            exception_matches.add(f"{file}:{parts[1]}")
                        else:
                            # For file:content format, just store file
                            exception_matches.add(file)
                else:
                    # Just a filename
                    exception_matches.add(match.strip())

    if verbose and exception_matches:
        print(f"{Colors.CYAN}Found {len(exception_matches)} exception patterns to filter out{Colors.RESET}")

    # Now run violation commands and filter out exceptions
    violations = []

    for cmd_info in violation_commands:
        command = cmd_info['command']
        description = cmd_info['description']

        if verbose:
            print(f"{Colors.GRAY}Running: {command}{Colors.RESET}")

        result = run_check_command(
            command, project_root, verbose, changed_files, changed_lines
        )
        if result and len(result) > 0:
            # Filter out exception matches
            filtered_matches = []
            for match in result:
                match_key = None
                # Extract file:line for comparison
                if ':' in match:
                    parts = match.split(':', 2)
                    if len(parts) >= 2:
                        file = parts[0]
                        if len(parts) == 3 and parts[1].isdigit():
                            match_key = f"{file}:{parts[1]}"
                        else:
                            match_key = file
                else:
                    match_key = match.strip()

                # Only include if not in exception set
                if match_key and match_key not in exception_matches:
                    filtered_matches.append(match)
                elif verbose:
                    print(f"{Colors.CYAN}Filtered out exception: {match_key}{Colors.RESET}")

            # Only add to violations if there are matches after filtering
            if filtered_matches:
                violations.append({
                    'command': command,
                    'description': description,
                    'matches': filtered_matches
                })

    return {
        'id': frontmatter.get('id'),
        'title': frontmatter.get('title'),
        'rule': extract_rule_text(content),
        'category': category,
        'filepath': f"{category}/{filename}",
        'severity': frontmatter.get('severity', 'warning'),
        'automation_result': frontmatter.get('automation_result', 'finding'),
        'violations': violations if violations else None
    }


def effective_severity(result: Dict) -> str:
    """Candidate searches require review and must never fail a run."""
    if result.get('automation_result') == 'candidate':
        return 'warning'
    return result.get('severity', 'warning')

def save_report(results: List[Dict], report_dir: Path, project_root: str, args, changed_files: Optional[set] = None) -> str:
    """Save analysis results to a markdown report."""
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    category_suffix = f"_{args.category}" if args.category else ""
    changed_suffix = "_changed" if args.changed else ""
    base_name = f"analysis_{timestamp}{category_suffix}{changed_suffix}"

    # Calculate summary stats
    total_violations = 0
    guidelines_with_violations = 0
    all_affected_files = set()
    error_count = 0
    warning_count = 0

    for result in results:
        if result['violations']:
            guidelines_with_violations += 1
            violation_count = sum(len(v['matches']) for v in result['violations'])
            total_violations += violation_count

            if effective_severity(result) == 'error':
                error_count += 1
            else:
                warning_count += 1

            for violation in result['violations']:
                by_file = parse_matches_to_by_file(violation['matches'])
                all_affected_files.update(by_file.keys())

    # Save markdown report
    md_path = report_dir / f"{base_name}.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# Design Guidelines Analysis Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"**Project:** `{project_root}`\n\n")
        if args.changed:
            f.write(f"**Mode:** Changed files only (compared to `{args.base_ref}`)\n\n")
            f.write(f"**Changed Files:** {len(changed_files) if changed_files else 0}\n\n")

        f.write("## Summary\n\n")
        f.write(f"- **Guidelines Checked:** {len(results)}\n")
        f.write(f"- **Violations:** {total_violations} across {guidelines_with_violations} guidelines\n")
        f.write(f"- **Affected Files:** {len(all_affected_files)}\n")
        if error_count > 0:
            f.write(f"- **Errors:** {error_count}\n")
        if warning_count > 0:
            f.write(f"- **Warnings:** {warning_count}\n")

        if total_violations == 0:
            f.write("\n✅ **All checks passed!**\n")
            f.write("\n## Detailed Results\n\n")
            f.write("All checks passed. No violations found.\n")
        else:
            f.write("\n## Detailed Results\n\n")

            for result in results:
                if result['violations']:
                    violation_count = sum(len(v['matches']) for v in result['violations'])
                    severity = effective_severity(result)
                    severity_emoji = "❌" if severity == 'error' else "⚠️"

                    f.write(f"### {severity_emoji} {result['title']}\n\n")
                    f.write(f"**Severity:** {severity}\n\n")
                    f.write(f"**Violations:** {violation_count}\n\n")

                    if result['rule']:
                        f.write(f"**Rule:** {result['rule']}\n\n")

                    for violation in result['violations']:
                        if violation['description']:
                            f.write(f"#### {violation['description']}\n\n")

                        by_file = parse_matches_to_by_file(violation['matches'])
                        for file, lines in list(by_file.items())[:10]:
                            ui_url = get_route_for_file(file, project_root)
                            url_link = f" → [View in app]({ui_url})" if ui_url else ""
                            f.write(f"- **{file}** ({len(lines)} violations){url_link}\n")
                            for line in lines[:3]:
                                if line['line']:
                                    f.write(f"  - Line {line['line']}: `{line['content'][:100]}`\n")
                                else:
                                    f.write(f"  - `{line['content'][:100]}`\n")

                    f.write("\n")

    # Save HTML report
    html_path = report_dir / f"{base_name}.html"
    save_html_report(html_path, results, total_violations, guidelines_with_violations,
                     all_affected_files, error_count, warning_count, project_root, args, changed_files)

    return str(md_path), str(html_path)

def save_html_report(html_path: Path, results: List[Dict], total_violations: int,
                     guidelines_with_violations: int, all_affected_files: set,
                     error_count: int, warning_count: int, project_root: str,
                     args, changed_files: Optional[set] = None):
    """Generate an HTML version of the report with clickable links."""

    with open(html_path, 'w', encoding='utf-8') as f:
        # HTML header and styles
        f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Design Guidelines Analysis Report</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        h1 {
            color: #1a1a1a;
            border-bottom: 3px solid #0066cc;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }

        h2 {
            color: #2c3e50;
            margin-top: 30px;
            margin-bottom: 15px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 8px;
        }

        h3 {
            color: #34495e;
            margin-top: 25px;
            margin-bottom: 10px;
        }

        h4 {
            color: #555;
            margin-top: 15px;
            margin-bottom: 8px;
            font-size: 1.05em;
        }

        .meta {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
            border-left: 4px solid #0066cc;
        }

        .meta p {
            margin: 5px 0;
        }

        .meta strong {
            color: #2c3e50;
        }

        .summary {
            background: #e8f4f8;
            padding: 20px;
            border-radius: 4px;
            margin-bottom: 30px;
        }

        .summary ul {
            list-style: none;
            padding-left: 0;
        }

        .summary li {
            padding: 5px 0;
            font-size: 1.05em;
        }

        .guideline {
            margin-bottom: 40px;
            padding: 20px;
            background: #fafafa;
            border-radius: 6px;
            border-left: 4px solid #ddd;
        }

        .guideline.error {
            border-left-color: #dc3545;
            background: #fff5f5;
        }

        .guideline.warning {
            border-left-color: #ffc107;
            background: #fffbf0;
        }

        .guideline-header {
            display: flex;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }

        .guideline-title {
            flex: 1;
        }

        .severity-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 600;
        }

        .severity-badge.error {
            background: #dc3545;
            color: white;
        }

        .severity-badge.warning {
            background: #ffc107;
            color: #000;
        }

        .guideline-link {
            display: inline-flex;
            align-items: center;
            padding: 6px 12px;
            background: #6c757d;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
            transition: background 0.2s;
        }

        .guideline-link:hover {
            background: #545b62;
        }

        .guideline-link::before {
            content: '📖 ';
            margin-right: 4px;
        }

        .violation-count {
            color: #666;
            font-size: 0.9em;
        }

        .rule {
            background: white;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 15px;
            border: 1px solid #e0e0e0;
            font-style: italic;
        }

        .violation-group {
            margin: 20px 0;
        }

        .file-list {
            list-style: none;
            margin: 10px 0;
        }

        .file-item {
            background: white;
            margin: 8px 0;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
        }

        .file-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
            flex-wrap: wrap;
            gap: 8px;
        }

        .file-name {
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.9em;
            color: #0066cc;
            font-weight: 600;
        }

        .links {
            display: flex;
            gap: 8px;
        }

        .app-link {
            display: inline-flex;
            align-items: center;
            padding: 6px 12px;
            background: #0066cc;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
            transition: background 0.2s;
        }

        .app-link:hover {
            background: #0052a3;
        }

        .app-link::before {
            content: '🔗 ';
            margin-right: 4px;
        }

        .code-line {
            font-family: 'Monaco', 'Menlo', monospace;
            font-size: 0.85em;
            background: #f8f9fa;
            padding: 6px 10px;
            margin: 4px 0;
            border-radius: 3px;
            border-left: 3px solid #dee2e6;
            overflow-x: auto;
        }

        .line-number {
            color: #6c757d;
            margin-right: 10px;
            font-weight: 600;
        }

        .all-pass {
            background: #d4edda;
            color: #155724;
            padding: 20px;
            border-radius: 4px;
            text-align: center;
            font-size: 1.2em;
            border: 2px solid #c3e6cb;
        }

        @media (max-width: 768px) {
            .container {
                padding: 20px;
            }

            .file-header {
                flex-direction: column;
                align-items: flex-start;
            }

            .links {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Design Guidelines Analysis Report</h1>

        <div class="meta">
            <p><strong>Date:</strong> """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
            <p><strong>Project:</strong> <code>""" + project_root + """</code></p>
""")

        if args.changed:
            f.write(f"""            <p><strong>Mode:</strong> Changed files only (compared to <code>{args.base_ref}</code>)</p>
            <p><strong>Changed Files:</strong> {len(changed_files) if changed_files else 0}</p>
""")

        f.write("""        </div>

        <div class="summary">
            <h2>Summary</h2>
            <ul>
                <li><strong>Guidelines Checked:</strong> """ + str(len(results)) + """</li>
                <li><strong>Violations:</strong> """ + str(total_violations) + """ across """ + str(guidelines_with_violations) + """ guidelines</li>
                <li><strong>Affected Files:</strong> """ + str(len(all_affected_files)) + """</li>
""")

        if error_count > 0:
            f.write(f"                <li><strong>Errors:</strong> {error_count}</li>\n")
        if warning_count > 0:
            f.write(f"                <li><strong>Warnings:</strong> {warning_count}</li>\n")

        f.write("""            </ul>
        </div>

        <h2>Detailed Results</h2>
""")

        if total_violations == 0:
            f.write("""        <div class="all-pass">
            ✅ All checks passed! No violations found.
        </div>
""")
        else:
            for result in results:
                if result['violations']:
                    violation_count = sum(len(v['matches']) for v in result['violations'])
                    severity = effective_severity(result)
                    severity_class = 'error' if severity == 'error' else 'warning'
                    severity_emoji = "❌" if severity == 'error' else "⚠️"

                    # Get guideline info for link
                    guideline_id = result.get('id', '')
                    category = result.get('category', '')
                    guideline_link = f"../guidelines-html/{category}/{guideline_id}.html" if guideline_id and category else ""

                    f.write(f"""        <div class="guideline {severity_class}">
            <div class="guideline-header">
                <div class="guideline-title">
                    <h3>{severity_emoji} {result['title']}</h3>
                    <span class="violation-count">{violation_count} violations</span>
                </div>
                <span class="severity-badge {severity_class}">{severity.upper()}</span>
""")

                    if guideline_link:
                        f.write(f"""                <a href="{guideline_link}" class="guideline-link" target="_blank">View Guideline</a>
""")

                    f.write("""            </div>

""")

                    if result['rule']:
                        rule_text = result['rule'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        f.write(f"""            <div class="rule">
                <strong>Rule:</strong> {rule_text}
            </div>

""")

                    for violation in result['violations']:
                        if violation['description']:
                            desc_text = violation['description'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            f.write(f"""            <div class="violation-group">
                <h4>{desc_text}</h4>

""")

                        by_file = parse_matches_to_by_file(violation['matches'])
                        f.write("""                <ul class="file-list">\n""")

                        for file, lines in list(by_file.items())[:10]:
                            ui_url = get_route_for_file(file, project_root)

                            f.write(f"""                    <li class="file-item">
                        <div class="file-header">
                            <span class="file-name">{file}</span>
                            <div class="links">
""")

                            if ui_url:
                                f.write(f"""                                <a href="{ui_url}" class="app-link" target="_blank">View in app</a>
""")

                            if guideline_link:
                                f.write(f"""                                <a href="{guideline_link}" class="guideline-link" target="_blank">View Guideline</a>
""")

                            f.write("""                            </div>
                        </div>
""")

                            for line in lines[:3]:
                                content = line['content'][:100]
                                # Escape HTML
                                content = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

                                if line['line']:
                                    f.write(f"""                        <div class="code-line">
                            <span class="line-number">Line {line['line']}:</span>
                            <code>{content}</code>
                        </div>
""")
                                else:
                                    f.write(f"""                        <div class="code-line">
                            <code>{content}</code>
                        </div>
""")

                            f.write("""                    </li>
""")

                        f.write("""                </ul>
            </div>

""")

                    f.write("""        </div>

""")

        f.write("""    </div>
</body>
</html>
""")


def build_evaluator_report(results: List[Dict]) -> Dict:
    """Return the stable JSON contract consumed by uxd-prototype-evaluate."""
    source_violations = []
    error_guidelines = 0
    warning_guidelines = 0

    for result in results:
        violations = result['violations'] or []
        if not violations:
            continue

        severity = effective_severity(result)
        is_candidate = result.get('automation_result') == 'candidate'

        if severity == 'error':
            error_guidelines += 1
        else:
            warning_guidelines += 1

        for violation in violations:
            for file, locations in parse_matches_to_by_file(violation['matches']).items():
                for location in locations:
                    source_violations.append({
                        'guideline_id': result['id'],
                        'guideline_title': result['title'],
                        'category': result['category'],
                        'severity': severity,
                        'verdict': 'FLAGGED' if is_candidate or severity == 'warning' else 'VIOLATION',
                        'confidence': 'low' if is_candidate else 'high',
                        'review_candidate': is_candidate,
                        'file': file,
                        'line': int(location['line']) if location['line'] else None,
                        'property': result['id'],
                        'value': location['content'],
                        'description': violation['description'],
                        'suggestion': result['rule'],
                        'check_method': 'automated_candidate' if is_candidate else 'automated',
                    })

    passes = len(results) - error_guidelines - warning_guidelines
    return {
        'source': 'uxd-consistency-check',
        'degraded': False,
        'checked_at': datetime.now().astimezone().isoformat(),
        'guidelines_version': (Path(__file__).parent.parent / 'VERSION').read_text().strip(),
        'source_mode': {
            'ran': True,
            'violations': source_violations,
        },
        'visual_mode': {
            'ran': False,
            'screenshots_checked': 0,
            'findings': [],
        },
        'summary': {
            'total_guidelines_checked': len(results),
            'violations': error_guidelines,
            'warnings': warning_guidelines,
            'passes': passes,
        },
    }

def main():
    parser = argparse.ArgumentParser(description='Design Guidelines Checker')
    parser.add_argument('--src', '--source-dir', dest='source_dir',
                        help='Path to source code directory to analyze')
    parser.add_argument('--category', help='Check only specific category')
    parser.add_argument('--guideline', help='Check only specific guideline')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')
    parser.add_argument('--report-dir', default='reports',
                        help='Directory to save analysis reports (default: reports)')
    parser.add_argument('--changed', action='store_true',
                        help='Only check files changed compared to base branch')
    parser.add_argument('--base-ref', default='main',
                        help='Base git ref for comparison (default: main)')
    parser.add_argument('--json-output', action='store_true',
                        help='Write the evaluator consistency-report JSON to stdout')
    parser.add_argument('--json-file',
                        help='Write the evaluator consistency-report JSON to this path')
    args = parser.parse_args()
    evaluator_output = args.json_output or bool(args.json_file)

    if evaluator_output:
        args.report_dir = None
    else:
        print(f"{Colors.BOLD}{Colors.BLUE}Design Guidelines Checker{Colors.RESET}\n")

    # Determine project root
    if args.source_dir:
        project_root = Path(args.source_dir).resolve()
        if not project_root.exists():
            print(f"{Colors.RED}Error: Source directory not found: {args.source_dir}{Colors.RESET}", file=sys.stderr)
            sys.exit(1)
    else:
        # Default: assume project is parent of design-checker/
        design_checker_root = Path(__file__).parent.parent.parent.resolve()
        project_root = design_checker_root.parent.resolve()
        if not evaluator_output:
            print(f"{Colors.YELLOW}Warning: No --src specified, using default: {project_root}{Colors.RESET}\n")

    # Determine check_cwd - the working directory for grep commands
    # If project_root points to a 'src' directory, use its parent since
    # grep commands in guidelines reference 'src/' explicitly
    check_cwd = project_root.parent if project_root.name == 'src' else project_root

    # Guidelines are always in consistency-checker/guidelines/
    design_checker_root = Path(__file__).parent.parent.resolve()
    guidelines_dir = design_checker_root / 'guidelines'

    # Discover categories so the guideline corpus can grow without requiring a
    # matching source-code change in the analyzer.
    categories = sorted(
        directory.name for directory in guidelines_dir.iterdir() if directory.is_dir()
    )
    categories_to_check = [args.category] if args.category else categories

    # Get changed files if --changed flag is set
    changed_files = None
    changed_lines = None
    if args.changed:
        changed_files = get_changed_files(args.base_ref, str(check_cwd), args.verbose)
        if changed_files is None:
            print(f"{Colors.RED}Error: Cannot use --changed mode (not in git repo or git command failed){Colors.RESET}", file=sys.stderr)
            sys.exit(1)
        if not changed_files:
            if evaluator_output:
                report_json = json.dumps(build_evaluator_report([]), indent=2)
                if args.json_file:
                    output_path = Path(args.json_file)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(report_json + '\n')
                else:
                    print(report_json)
            else:
                print(f"{Colors.YELLOW}No changed files found compared to {args.base_ref}{Colors.RESET}")
                print(f"{Colors.GREEN}All checks passed! (no files to check){Colors.RESET}")
            sys.exit(0)
        if not evaluator_output:
            print(f"{Colors.CYAN}Analyzing {len(changed_files)} changed file(s) compared to {args.base_ref}{Colors.RESET}\n")
        changed_lines = get_changed_lines(args.base_ref, str(check_cwd), args.verbose)
        if changed_lines is None:
            print(f"{Colors.RED}Error: Cannot resolve changed lines compared to {args.base_ref}{Colors.RESET}", file=sys.stderr)
            sys.exit(1)

        if not args.category:
            applicable = detect_applicable_categories(changed_files, str(check_cwd))
            if applicable:
                categories_to_check = [
                    category for category in categories if category in applicable
                ]
                if args.verbose and not evaluator_output:
                    print(
                        f"{Colors.CYAN}Applicable categories: "
                        f"{', '.join(categories_to_check)}{Colors.RESET}\n"
                    )

    results = []

    for category in categories_to_check:
        category_path = guidelines_dir / category

        if not category_path.exists():
            if not evaluator_output:
                print(f"{Colors.RED}Error: Category not found: {category}{Colors.RESET}")
            continue

        for md_file in category_path.glob('*.md'):
            if args.guideline and args.guideline not in md_file.name:
                continue

            result = check_guideline(
                category,
                md_file.name,
                str(check_cwd),
                args.verbose,
                changed_files,
                changed_lines,
            )
            if result:
                results.append(result)

    # Calculate summary statistics
    total_violations = 0
    guidelines_with_violations = 0
    all_affected_files = set()
    error_count = 0
    warning_count = 0

    for result in results:
        if result['violations']:
            guidelines_with_violations += 1
            violation_count = sum(len(v['matches']) for v in result['violations'])
            total_violations += violation_count

            # Track severity
            if effective_severity(result) == 'error':
                error_count += 1
            else:
                warning_count += 1

            # Track affected files
            for violation in result['violations']:
                by_file = parse_matches_to_by_file(violation['matches'])
                all_affected_files.update(by_file.keys())

    if evaluator_output:
        report_json = json.dumps(build_evaluator_report(results), indent=2)
        if args.json_file:
            output_path = Path(args.json_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report_json + '\n')
        else:
            print(report_json)
        sys.exit(1 if error_count > 0 else 0)

    # Print summary first
    print(f"{Colors.BOLD}Summary{Colors.RESET}")
    print(f"  Checked: {len(results)} guideline{'s' if len(results) != 1 else ''}")
    print(f"  Violations: {total_violations} across {guidelines_with_violations} guideline{'s' if guidelines_with_violations != 1 else ''}")
    print(f"  Affected files: {len(all_affected_files)}")

    if error_count > 0 or warning_count > 0:
        severity_parts = []
        if error_count > 0:
            severity_parts.append(f"{error_count} error{'s' if error_count != 1 else ''}")
        if warning_count > 0:
            severity_parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
        print(f"  Severity: {', '.join(severity_parts)}")

    # Save report (always, regardless of violations)
    if args.report_dir:
        md_path, html_path = save_report(results, Path(args.report_dir), str(project_root), args, changed_files)
        print(f"\n{Colors.GREEN}Reports saved:{Colors.RESET}")
        print(f"  Markdown: {md_path}")
        print(f"  HTML: {html_path}")

    if total_violations == 0:
        print(f"\n{Colors.GREEN}All checks passed!{Colors.RESET}")
        sys.exit(0)

    # Print detailed results
    print(f"\n{Colors.BOLD}Detailed Results{Colors.RESET}\n")

    for result in results:
        if not result['violations']:
            print(f"{Colors.GREEN}✓{Colors.RESET} {result['title']}")
        else:
            violation_count = sum(len(v['matches']) for v in result['violations'])

            severity_color = Colors.RED if effective_severity(result) == 'error' else Colors.YELLOW
            print(f"{severity_color}✗{Colors.RESET} {result['title']} {Colors.GRAY}({violation_count} violation{'s' if violation_count > 1 else ''}){Colors.RESET}")

            if args.verbose:
                # Show rule explanation
                if result['rule']:
                    print(f"  {Colors.YELLOW}Rule:{Colors.RESET} {result['rule']}")

                # Print each check with violations
                for violation in result['violations']:
                    if violation['description']:
                        print(f"\n  {Colors.BOLD}↳{Colors.RESET} {violation['description']}")

                    by_file = parse_matches_to_by_file(violation['matches'])
                    print_file_group(by_file, str(project_root))

                print('')
            else:
                # In non-verbose mode, show file-level summary
                all_files = {}
                for violation in result['violations']:
                    by_file = parse_matches_to_by_file(violation['matches'])
                    for file, lines in by_file.items():
                        if file not in all_files:
                            all_files[file] = 0
                        all_files[file] += len(lines)

                # Print up to 5 files with violation counts
                MAX_FILES_SUMMARY = 5
                file_items = list(all_files.items())[:MAX_FILES_SUMMARY]

                for file, count in file_items:
                    abs_file = os.path.join(str(project_root), file)
                    rel_file = os.path.relpath(abs_file, str(project_root))
                    ui_url = get_route_for_file(rel_file, project_root)
                    url_suffix = f" {Colors.CYAN}{ui_url}{Colors.RESET}" if ui_url else ""

                    print(f"    {Colors.BLUE}{rel_file}{Colors.RESET} {Colors.GRAY}({count}){Colors.RESET}{url_suffix}")

                if len(all_files) > MAX_FILES_SUMMARY:
                    remaining = len(all_files) - MAX_FILES_SUMMARY
                    print(f"    {Colors.GRAY}... and {remaining} more file{'s' if remaining > 1 else ''}{Colors.RESET}")

                print('')

    # Add help text for non-verbose mode
    if not args.verbose:
        print(f"\n{Colors.YELLOW}Run with --verbose (-v) to see violation locations, rules, and UI links.{Colors.RESET}")

    sys.exit(1 if error_count > 0 else 0)

if __name__ == '__main__':
    main()

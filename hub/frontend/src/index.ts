// Orochi Hub dashboard bundle entry point.
//
// Imports every dashboard module in the exact load order used by
// hub/templates/hub/dashboard.html BEFORE the migration.
//
// All imports are side-effect-only: each module runs its top-level
// code (registering globals, attaching event listeners) exactly
// once at import time. The IIFE output format preserves classic-
// script semantics where top-level `var`/`function` become
// accessible across files through the shared window/global scope.
//
// Generated 2026-04-20 during big-bang TS migration.

import "./config";
import "./agent-icons";
import "./agent-badge";
import "./agent-badge-svg";
import "./channel-badge";
import "./app/state";
import "./app/members";
import "./app/channel-prefs";
import "./app/context-menus";
import "./app/agent-actions";
import "./app/utils";
import "./app/websocket";
import "./app/sidebar-agents";
import "./app/sidebar-channel-tree";
import "./app/sidebar-stats";
import "./app/keyboard";
import "./dms";
import "./workspace-dropdown";
import "./resources-tab/panel";
import "./resources-tab/tab";
import "./todo-tab/todo-tab-helpers";
import "./todo-tab/todo-tab-list";
import "./todo-tab/todo-tab-stats";
import "./workspaces-tab";
import "./pdf-thumbnail";
import "./chat/chat-state";
import "./chat/chat-attachments";
import "./chat/chat-markdown";
import "./chat/chat-render";
import "./chat/chat-history";
import "./chat/chat-composer";
import "./chat/chat-actions";
import "./mention";
import "./settings-tab";
import "./emoji-picker";
import "./filter/state";
import "./filter/runner";
import "./agents-tab/state";
import "./agents-tab/lamps";
import "./agents-tab/detail";
import "./agents-tab/controls";
import "./agents-tab/overview";
import "./connectivity-map";
import "./activity-tab/state";
import "./activity-tab/utils";
import "./activity-tab/data";
import "./activity-tab/hooks-panel";
import "./activity-tab/detail";
import "./activity-tab/detail-bind";
import "./activity-tab/channel-controls";
import "./activity-tab/multiselect";
import "./activity-tab/topology-arrows";
import "./activity-tab/topology-packets";
import "./activity-tab/topology-pulse";
import "./activity-tab/seekbar";
import "./activity-tab/zoompan";
import "./activity-tab/compose";
import "./activity-tab/topology-signature";
import "./activity-tab/topology-edges";
import "./activity-tab/topology-nodes";
import "./activity-tab/topology-pool";
import "./activity-tab/topology";
import "./activity-tab/row";
import "./activity-tab/click";
import "./activity-tab/edge-menu";
import "./activity-tab/grid-click";
import "./activity-tab/grid-mouse";
import "./activity-tab/grid-ctx";
import "./activity-tab/grid-hover";
import "./activity-tab/grid-delegation";
import "./activity-tab/controls";
import "./activity-tab/init";
import "./app/sidebar-memory";
import "./viz-tab";
import "./upload";
import "./files-tab/files-tab-core";
import "./files-tab/files-tab-grid";
import "./releases-tab/state";
import "./releases-tab/runner";
import "./reactions";
import "./threads/state";
import "./threads/panel";
import "./sketch";
import "./webcam";
import "./voice-input";
import "./terminal-tab";
import "./tabs";
import "./init";
import "./sidebar-fold";
import "./sw-register";
import "./push";
import "./element-inspector/core";
import "./element-inspector/overlay";
import "./element-inspector/picker";
import "./element-inspector/scanner";
import "./element-inspector/selection";
import "./element-inspector/main";
import "./search-palette";
import "./feed-scroll-btns";
import "./feed-nav";

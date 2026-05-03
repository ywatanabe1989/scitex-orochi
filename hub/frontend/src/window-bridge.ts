// @ts-nocheck
// Single bridge from ES modules back to HTML inline-handler namespace.
// Every symbol listed here is referenced from an on*= handler in one
// of the hub/templates/hub/ templates. If you add a new such handler,
// add the symbol here AND export it from its defining module.

import { openAvatarPicker, openHumanAvatarPicker, openHumanAvatarTextEditor } from "./agent-icons";
import { purgeStaleAgents, toggleClaudeMd } from "./agents-tab/overview";
import { closeChannelExport, doCopyChannelExport, doChannelExport, openChannelExport } from "./app/agent-actions";
import { closeChannelTopicEdit, closeMembersPanel, openChannelTopicEdit, saveChannelTopic, toggleMembersPanel } from "./app/members";
import { killAgent, restartAgent, togglePinAgent } from "./app/sidebar-agents";
import { escapeHtml } from "./app/utils";
import { deleteMessage, startEditMessage } from "./chat/chat-actions";
import { jumpToMsg } from "./chat/chat-attachments";
import { chatFilterApply } from "./chat/chat-state";
import { closeImgViewer, filesSetQuery, filesSetView, filesTogglePreview, imgViewerNav, openImgViewer } from "./files-tab/files-tab-core";
import { closePdfViewer, filesClearSelection, filesDownloadSelected, filesHandleClick } from "./files-tab/files-tab-grid";
import { removeTag } from "./filter/state";
import { togglePush } from "./push";
import { openReactionPicker, toggleReaction } from "./reactions";
import { copyToken, toggleToken } from "./settings";
import { closeThreadPanel, openThreadForMessage, sendThreadReply } from "./threads/panel";
import { copyThreadPermalink } from "./threads/state";

declare const window: any;
Object.assign(window, {
  chatFilterApply,
  closeChannelExport,
  closeChannelTopicEdit,
  closeImgViewer,
  closeMembersPanel,
  closePdfViewer,
  closeThreadPanel,
  copyThreadPermalink,
  copyToken,
  deleteMessage,
  doCopyChannelExport,
  doChannelExport,
  escapeHtml,
  filesClearSelection,
  filesDownloadSelected,
  filesHandleClick,
  filesSetQuery,
  filesSetView,
  filesTogglePreview,
  imgViewerNav,
  jumpToMsg,
  killAgent,
  openAvatarPicker,
  openChannelExport,
  openChannelTopicEdit,
  openHumanAvatarPicker,
  openHumanAvatarTextEditor,
  openImgViewer,
  openReactionPicker,
  openThreadForMessage,
  purgeStaleAgents,
  removeTag,
  restartAgent,
  saveChannelTopic,
  sendThreadReply,
  startEditMessage,
  toggleClaudeMd,
  toggleMembersPanel,
  togglePinAgent,
  togglePush,
  toggleReaction,
  toggleToken,
});

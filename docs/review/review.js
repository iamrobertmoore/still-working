'use strict';
const data = JSON.parse(document.getElementById('review-data').textContent);
let previousDownload;
const reviewForm = document.getElementById('review-form');
reviewForm.addEventListener('input', () => {
  document.getElementById('review-result').hidden = true;
  document.getElementById('download').hidden = true;
  document.getElementById('error').textContent = '';
  if (previousDownload) { URL.revokeObjectURL(previousDownload);previousDownload = null; }
});
const count = (number, singular, plural = `${singular}s`) => `${number} ${number === 1 ? singular : plural}`;
reviewForm.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  const decision = new FormData(form).get('decision');
  const reviewer = document.getElementById('reviewer').value.trim();
  const reason = document.getElementById('reason').value.trim();
  const error = document.getElementById('error');
  error.textContent = '';
  if (reviewer.length < 2 || reason.length < 2) {
    error.textContent = 'Add a reviewer and a short description of the check.';
    return;
  }
  const unsure = decision === 'unsure';
  const approved = decision === 'approve';
  const title = document.getElementById('result-title');
  const copy = document.getElementById('result-copy');
  const metrics = document.getElementById('result-metrics');
  const details = document.getElementById('note-details');
  const download = document.getElementById('download');
  details.hidden = true;download.hidden = true;metrics.textContent = '';
  if (previousDownload) { URL.revokeObjectURL(previousDownload);previousDownload = null; }
  title.textContent = unsure ? 'Still waiting for a person.' : approved ? 'Dependency confirmed for this case.' : 'This case can be closed.';
  copy.textContent = unsure ? 'No approval has been created. Keep the case pending until the dependency can be checked.' : data.mode === 'example' ? 'The saved AWS response below shows what this review decision allowed. Your click has not contacted AWS or changed the live queue.' : 'Your review is ready to download. It takes effect only after the project operator imports it and the daily caller processes this pending case.';
  if (data.mode === 'example') {
    const response = data.proof[unsure ? 'held' : approved ? 'approved' : 'dismissed'].result;
    metrics.textContent = `${count(response.agent_runs, 'agent run')} using a model · ${count(response.notes.length, 'note')} rendered · ${count(response.pending_routines.length, 'routine')} pending`;
    if (response.note) {
      document.getElementById('result-note').textContent = response.note;
      details.hidden = false;
    }
  }
  if (!unsure) {
    const artifact = {mode: data.mode, decisions:[{case_id:data.case_id,decision,reviewer,reason}]};
    previousDownload = URL.createObjectURL(new Blob([JSON.stringify(artifact,null,2)+'\n'],{type:'application/json'}));
    download.href = previousDownload;
    download.download = data.mode === 'example' ? 'still-working-example-review.json' : 'still-working-review.json';
    download.hidden = false;
  }
  document.getElementById('review-result').hidden = false;
});

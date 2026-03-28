const https = require('https');

function post(path, data, cookie) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const opts = {
      hostname: 'hqin.substack.com',
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
        'Cookie': cookie,
        'User-Agent': 'Mozilla/5.0'
      }
    };
    const req = https.request(opts, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve({ status: res.statusCode, body: d }));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

const COOKIE = 'substack.sid=s%3AEAHrFBEKZKJblBvGc6ZfTdoxVLW_YrMo.9%2B%2BgkKSXU7pLLYECR%2BWKiNqnfcxD5RaVkXg9vkCxKbE';

const p1text = 'Beauty cannot not occur — when construct fully unfolds, beauty is not something that might happen. It cannot not happen.';
const p2text = "Beauty cannot not develop — the Remainder Overflow Principle: every level's full unfolding exposes remainders the level cannot close. Corollary: there is no supreme beauty.";
const p3text = 'Beauty cannot not be questioned — no supreme beauty means the question "what is beauty" can never be closed.';
const artistText = 'the artist died not from incompetence but from breakage at every step of this chain. The prescription is to restore the breadth of feeling, the openness of pursuit, and the capacity to be questioned.';
const riverText = "Kant's Critique of Judgment built a bridge between nature and freedom. SAE's Judgment and Aesthetics attempts something different: not bridging two separate domains, but showing that beauty from 0DD to 16DD is the same river at different stretches. The bridge is not built between two separated banks. The bridge is the river itself.";

const draftBody = {
  draft_title: 'SAE Judgment and Aesthetics — In Tribute to Kant',
  draft_subtitle: 'Beauty is the structural state that cannot not occur when construct fully unfolds at a given dimension. Three propositions, six theorems, thirteen beauties, subject conditions. The prescription for The Artist Is Dead.',
  draft_body: JSON.stringify({
    type: 'doc',
    content: [
      {type:'paragraph', content:[
        {type:'text', marks:[{type:'bold'}], text:'SAE Judgment and Aesthetics'},
        {type:'text', text:' — In Tribute to Kant'}
      ]},
      {type:'paragraph', content:[
        {type:'text', text:'DOI: '},
        {type:'text', marks:[{type:'link', attrs:{href:'https://doi.org/10.5281/zenodo.19296710'}}], text:'10.5281/zenodo.19296710'}
      ]},
      {type:'paragraph', content:[
        {type:'text', marks:[{type:'link', attrs:{href:'https://self-as-an-end.net/papers/sae-judgment-aesthetics.html'}}], text:'Read on self-as-an-end.net'}
      ]},
      {type:'horizontalRule'},
      {type:'paragraph', content:[
        {type:'text', text:'This paper presents the general framework of SAE aesthetics. Beauty is not aesthetic judgment, not sensory experience, not the product of art. '},
        {type:'text', marks:[{type:'bold'}], text:'Beauty is the structural state that cannot not occur when a construct fully unfolds at a given dimension.'}
      ]},
      {type:'paragraph', content:[{type:'text', text:'Three propositions of aesthetics:'}]},
      {type:'bulletList', content:[
        {type:'listItem', content:[{type:'paragraph', content:[
          {type:'text', marks:[{type:'bold'}], text:'Proposition One: '},
          {type:'text', text: p1text}
        ]}]},
        {type:'listItem', content:[{type:'paragraph', content:[
          {type:'text', marks:[{type:'bold'}], text:'Proposition Two: '},
          {type:'text', text: p2text}
        ]}]},
        {type:'listItem', content:[{type:'paragraph', content:[
          {type:'text', marks:[{type:'bold'}], text:'Proposition Three: '},
          {type:'text', text: p3text}
        ]}]}
      ]},
      {type:'paragraph', content:[
        {type:'text', text:'Six core theorems constitute the mechanics of SAE aesthetics: Chisel-Construct Identity, Internality of Context, Anti-Correlation with Alien Control, Dimensional Irreducibility, Conservation of Locus, and Thickening.'}
      ]},
      {type:'paragraph', content:[
        {type:'text', text:'The SAE dimensional sequence (0DD-16DD) generates '},
        {type:'text', marks:[{type:'bold'}], text:'thirteen forms of beauty'},
        {type:'text', text:' — from the Beauty of Chaos (0DD) through Philosophy, Mathematics, Physics, Causation, Biology, Reproduction, Perception, Cognition, Self, Purpose, Non-Doubt, to the Beauty of Mutual Non-Doubt (16DD). The chain undergoes a phase transition between 12DD and 13DD.'}
      ]},
      {type:'paragraph', content:[
        {type:'text', text:'Subject conditions form a derivation chain: Cannot not feel beauty (audacity) → Cannot not pursue beauty → Cannot not be questioned (ignorance). This provides the prescription for '},
        {type:'text', marks:[{type:'link', attrs:{href:'https://doi.org/10.5281/zenodo.19104160'}}], text:'The Artist Is Dead'},
        {type:'text', text:': '},
        {type:'text', text: artistText}
      ]},
      {type:'horizontalRule'},
      {type:'paragraph', content:[{type:'text', marks:[{type:'bold'}], text:'On Kant:'}]},
      {type:'paragraph', content:[{type:'text', text: riverText}]},
      {type:'horizontalRule'},
      {type:'paragraph', content:[
        {type:'text', text:'This paper is the third pillar of the SAE system, alongside SAE epistemology (Methodology Papers I-III) and SAE ethics (One\'s Own Law).'}
      ]},
      {type:'paragraph', content:[
        {type:'text', marks:[{type:'link', attrs:{href:'https://self-as-an-end.net/papers/sae-judgment-aesthetics.html'}}], text:'Full paper (bilingual EN/ZH)'}
      ]}
    ]
  }),
  draft_bylines: [{id: 452619024, is_lead: true}]
};

post('/api/v1/drafts', draftBody, COOKIE)
  .then(r => {
    console.log('Draft status:', r.status);
    const draft = JSON.parse(r.body);
    console.log('Draft id:', draft.id);
    return post('/api/v1/drafts/' + draft.id + '/publish', {send_email: false, share_automatically: false}, COOKIE)
      .then(r2 => {
        console.log('Publish status:', r2.status);
        const pub = JSON.parse(r2.body);
        console.log('Slug:', pub.slug);
        console.log('Post id:', pub.id);
      });
  })
  .catch(e => console.error(e));

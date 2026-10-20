// schema.org entities shared by the prerendered and client-rendered JSON-LD.
// Each carries an absolute @id and is declared in full once per page; any other
// use on the page is a bare {"@id": ...} reference. The Person is declared in
// web/index.html (the template every page inherits) — keep its @id in sync with
// PERSON_ID.
export const SITE = "https://koyracloud.com";
export const PERSON_ID = `${SITE}/#arshad-ansari`;

// Hikmah Technologies is declared in full in web/index.html (id #organization,
// on every page), so the blog JSON-LD only references it — keep the id in sync.
export const HIKMAH_ORG_ID = `${SITE}/#organization`;
export const HIKMAH_ORG = { "@id": HIKMAH_ORG_ID };

export const KOYRACLOUD_ORG = {
  "@type": "Organization",
  "@id": `${SITE}/#koyracloud`,
  name: "koyracloud",
  url: SITE,
};

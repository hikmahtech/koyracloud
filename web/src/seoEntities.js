// schema.org entities shared by the prerendered and client-rendered JSON-LD.
// Each carries an absolute @id and is declared in full once per page; any other
// use on the page is a bare {"@id": ...} reference. The Person is declared in
// web/index.html (the template every page inherits) — keep its @id in sync with
// PERSON_ID.
export const SITE = "https://koyracloud.com";
export const PERSON_ID = `${SITE}/#arshad-ansari`;

export const HIKMAH_ORG = {
  "@type": "Organization",
  "@id": `${SITE}/#hikmah-technologies`,
  name: "Hikmah Technologies",
  url: "https://hikmahtechnologies.com",
};

export const KOYRACLOUD_ORG = {
  "@type": "Organization",
  "@id": `${SITE}/#koyracloud`,
  name: "koyracloud",
  url: SITE,
};

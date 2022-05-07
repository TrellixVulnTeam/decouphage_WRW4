import datetime
import os
import re
from pathlib import Path

from Bio import SeqIO
from Bio.SeqFeature import SeqFeature, FeatureLocation

from src import tools
from src.annotate import Annotate
from src.output import write_gbk


class Pipeline(object):
    def __init__(self, input_file, prodigal, threads, output_file):
        self.use_prodigal = prodigal
        self.blast_threads = threads
        self.output_file = output_file
        self.contig_file = input_file

        self.genome = None
        self.orf_map = None
        self.run()

    def orf_calling(self):
        if self.use_prodigal:
            self.orf_map = tools.run_prodigal(self.contig_file)
        else:
            self.orf_map = tools.run_phanotate(self.contig_file)

    def run(self):
        self.load_genome()
        self.cleanup_query_file()
        self.orf_calling()
        self.load_features()
        self.prepare_query_file()
        tools.run_blast(self.blast_threads)

        qualifiers = {record["qseqid"]: record for record in Annotate().run()}
        self.enrich_features(qualifiers)

        write_gbk(self.genome.values(), self.output_file)

    def enrich_features(self, qualifiers):
        for contig in self.genome.values():
            for feature in contig.features:
                blast_result = qualifiers.get(int(feature.id), {})

                product = blast_result.get("stitle", "Unknown")
                pattern = r"\[.*?\]"
                product = re.sub(pattern, "", product).rstrip()
                product = product.replace("TPA: MAG TPA", "")

                tag = "PREF_{l:04d}".format(l=int(feature.id))

                quals = {
                    "gene": feature.id,
                    "product": product,
                    "locus_tag": tag,
                    "translation": self.cleanup_sequence(feature, contig),
                    "protein_id": blast_result.get("sseqid", "N/A"),
                }
                feature.qualifiers = quals

    def load_features(self):
        for contig_label, orf_list in self.orf_map.items():
            contig = self.genome[contig_label]
            for orf in orf_list:
                idx, start, end, strand = orf.split("_")
                feature = SeqFeature(
                    FeatureLocation(int(start) - 1, int(end)),
                    strand=1 if strand == "+" else -1,
                    type="CDS",
                    qualifiers={},
                    id=idx[1:],
                )
                contig.features.append(feature)

    def load_genome(self):
        today_date = str(datetime.date.today().strftime("%d-%b-%Y")).upper()
        self.genome = SeqIO.to_dict(SeqIO.parse(self.contig_file, "fasta"))

        for contig in self.genome.values():
            contig.annotations = {"molecule_type": "DNA", "date": today_date}
            contig.id = Path(self.contig_file).stem

    def prepare_query_file(self):
        with open("tmp/query.fa", "a") as fh:
            for contig in self.genome.values():
                for feature in contig.features:
                    fh.write(f">{feature.id}\n")
                    fh.write(self.cleanup_sequence(feature, contig) + "\n")

    @staticmethod
    def cleanup_sequence(feature, contig):
        sequence = str(feature.extract(contig.seq).translate(table=11))
        if sequence.endswith("*"):
            sequence = sequence[:-1]
        return sequence

    @staticmethod
    def cleanup_query_file():
        try:
            os.mkdir("tmp")
        except Exception as err:
            pass

        with open("tmp/query.fa", "w") as fh:
            fh.write("")